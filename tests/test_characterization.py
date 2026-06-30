"""Engine and contract tests.

The engine needs the ``[analysis]`` extra (numpy/scipy/pandas); the ``dev`` extra installs it,
so — as with sqlalchemy in the Postgres tests — these import the optional deps directly.
"""

import numpy as np

from flapjack_data import (
    Assay,
    Chemical,
    Dna,
    InMemoryStorage,
    Measurement,
    Sample,
    Signal,
    Study,
    Supplement,
    Vector,
)
from flapjack_data.characterization import AnalysisSpec, AnalysisType, Selection, engine


def _seed() -> tuple[InMemoryStorage, dict]:
    store = InMemoryStorage()
    study = store.add(Study(name="demo"))
    assay = store.add(Assay(study_id=study.id, name="kinetic"))
    gfp = store.add(Signal(name="GFP", kind="fluorescence"))
    od = store.add(Signal(name="OD", kind="biomass"))
    dna = store.add(Dna(name="pTet-GFP"))
    vector = store.add(Vector(name="v1", dna_ids=[dna.id]))
    chem = store.add(Chemical(name="aTc"))

    samples = {}
    for conc in (0.0, 10.0):
        supp = store.add(Supplement(name=f"aTc-{conc}", chemical_id=chem.id, concentration=conc))
        sample = store.add(
            Sample(assay_id=assay.id, row=0, col=int(conc), vector_id=vector.id, supplement_ids=[supp.id])
        )
        samples[conc] = sample.id
        for t in np.linspace(0, 10, 40):
            store.add(
                Measurement(
                    sample_id=sample.id, signal_id=od.id, value=float(0.05 * np.exp(0.3 * t) + 0.02), time=float(t)
                )
            )
            store.add(
                Measurement(sample_id=sample.id, signal_id=gfp.id, value=float((20 + conc) * t + 5), time=float(t))
            )
    # A media blank (no vector, no strain) so background correction has something to subtract.
    blank = store.add(Sample(assay_id=assay.id, row=1, col=0))
    for t in np.linspace(0, 10, 40):
        store.add(Measurement(sample_id=blank.id, signal_id=od.id, value=0.02, time=float(t)))
        store.add(Measurement(sample_id=blank.id, signal_id=gfp.id, value=5.0, time=float(t)))

    return store, {"study": study.id, "gfp": gfp.id, "od": od.id, "chem": chem.id, **samples}


def test_mean_expression_subtracts_background() -> None:
    store, ids = _seed()
    spec = AnalysisSpec(type=AnalysisType.MEAN_EXPRESSION, selection=Selection(study_ids=[ids["study"]]))
    result = engine.run(spec, store, use_cache=False)

    gfp_rows = [d for d in result.data if d.signal_id == ids["gfp"]]
    assert len(gfp_rows) == 2  # one per real sample; blank dropped by bg correction
    assert all(d.time is None and d.metric == "Expression" for d in gfp_rows)
    # GFP for conc=0 is 20*t+5; the blank (5.0) is subtracted, so the mean is ~mean(20*t) ≈ 100.
    zero = next(d for d in gfp_rows if d.sample_id == ids[0.0])
    assert 90 < zero.value < 110


def test_velocity_is_time_series() -> None:
    store, ids = _seed()
    spec = AnalysisSpec(
        type=AnalysisType.VELOCITY,
        selection=Selection(study_ids=[ids["study"]], signal_ids=[ids["gfp"]]),
        pre_smoothing=11,
        post_smoothing=11,
    )
    result = engine.run(spec, store, use_cache=False)
    assert result.data and all(d.time is not None and d.metric == "Velocity" for d in result.data)
    # Velocity keeps background (the constant blank, whose velocity is ~0); the real samples'
    # GFP is monotonically increasing, so their velocity is positive.
    real = [d for d in result.data if d.sample_id in {ids[0.0], ids[10.0]}]
    assert real and all(d.value > 0 for d in real)


def test_induction_curve_carries_concentration() -> None:
    store, ids = _seed()
    spec = AnalysisSpec(
        type=AnalysisType.INDUCTION_CURVE,
        selection=Selection(study_ids=[ids["study"]], signal_ids=[ids["gfp"]]),
        analyte_id=ids["chem"],
        function=AnalysisType.MEAN_EXPRESSION,
    )
    result = engine.run(spec, store, use_cache=False)
    concentrations = sorted(d.concentration for d in result.data)
    assert concentrations == [0.0, 10.0]
    # Higher inducer → higher mean expression.
    by_conc = {d.concentration: d.value for d in result.data}
    assert by_conc[10.0] > by_conc[0.0]


def test_expression_rate_methods_run() -> None:
    store, ids = _seed()
    for analysis_type, kwargs in [
        (AnalysisType.EXPRESSION_RATE_INDIRECT, {"pre_smoothing": 11, "post_smoothing": 11}),
        (AnalysisType.EXPRESSION_RATE_INVERSE, {"n_gaussians": 6}),
        (AnalysisType.EXPRESSION_RATE_DIRECT, {}),
    ]:
        spec = AnalysisSpec(
            type=analysis_type,
            selection=Selection(study_ids=[ids["study"]], signal_ids=[ids["gfp"]]),
            biomass_signal_id=ids["od"],
            **kwargs,
        )
        result = engine.run(spec, store, use_cache=False)
        assert result.data, f"{analysis_type} produced no data"
        assert all(d.metric == "Rate" for d in result.data)


def test_persist_and_cache_roundtrip() -> None:
    store, ids = _seed()
    spec = AnalysisSpec(type=AnalysisType.MEAN_EXPRESSION, selection=Selection(study_ids=[ids["study"]]))

    persisted = engine.run(spec, store, persist=True)
    assert persisted.characterization.id is not None
    assert persisted.characterization.params_hash == spec.params_hash()
    assert len(persisted.data) == len(store.get_characterization_data(persisted.characterization.id))

    # A second run with the same spec is served from the cache (same persisted run id).
    cached = engine.run(spec, store)
    assert cached.characterization.id == persisted.characterization.id


def test_aggregate_pushdown_matches_raw_mean() -> None:
    store, ids = _seed()
    selection = Selection(study_ids=[ids["study"]], signal_ids=[ids["gfp"]])
    pushed = {
        (a.sample_id, a.signal_id): a.value for a in store.aggregate_measurements(func="mean", selection=selection)
    }

    measurements = store.query_measurements(study_id=ids["study"], signal_id=ids["gfp"])
    by_key: dict = {}
    for m in measurements:
        by_key.setdefault((m.sample_id, m.signal_id), []).append(m.value)
    expected = {k: sum(v) / len(v) for k, v in by_key.items()}

    assert pushed.keys() == expected.keys()
    assert all(abs(pushed[k] - expected[k]) < 1e-9 for k in expected)


def test_empty_selection_yields_no_frame() -> None:
    store, _ = _seed()
    assert list(store.measurement_frame(Selection())) == []
    assert store.aggregate_measurements(func="mean", selection=Selection()) == []
