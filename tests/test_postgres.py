from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from flapjack_data import (
    Assay,
    Characterization,
    CharacterizationDatum,
    Chemical,
    Measurement,
    Sample,
    Signal,
    Study,
    Supplement,
    Vector,
)
from flapjack_data.backends.postgres import PostgresStorage
from flapjack_data.characterization import Selection


def _engine():
    # In-memory SQLite shared across connections, so PostgresStorage exercises real SQL.
    return create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)


def _seed(store: PostgresStorage) -> dict[str, int]:
    study = store.add(Study(name="degradation tags"))
    assay = store.add(Assay(study_id=study.id, name="kinetic", machine="Clariostar"))
    gfp = store.add(Signal(name="GFP"))
    od = store.add(Signal(name="OD"))
    sample = store.add(Sample(assay_id=assay.id, row=0, col=0))
    for t in range(3):
        store.add(Measurement(sample_id=sample.id, signal_id=gfp.id, value=10.0 * t, time=float(t)))
        store.add(Measurement(sample_id=sample.id, signal_id=od.id, value=0.1 * t, time=float(t)))
    return {"study": study.id, "assay": assay.id, "gfp": gfp.id, "sample": sample.id}


def test_crud_and_query() -> None:
    store = PostgresStorage(_engine(), create=True)
    ids = _seed(store)

    fetched = store.get(Study, ids["study"])
    assert fetched is not None and fetched.name == "degradation tags"
    assert {s.name for s in store.list_all(Signal)} == {"GFP", "OD"}

    assert len(store.query_measurements(signal_id=ids["gfp"])) == 3
    assert len(store.query_measurements(study_id=ids["study"])) == 6
    assert len(store.query_measurements(assay_id=ids["assay"], signal_id=ids["gfp"])) == 3


def test_owner_scoping_isolates() -> None:
    engine = _engine()
    PostgresStorage(engine, create=True)  # create schema once
    org_a = PostgresStorage(engine, owner="org-a")
    org_b = PostgresStorage(engine, owner="org-b")

    study = org_a.add(Study(name="a only"))
    assert study.owner == "org-a"

    assert len(org_a.list_all(Study)) == 1
    assert org_b.list_all(Study) == []
    assert org_b.get(Study, study.id) is None


def _seed_characterization(store: PostgresStorage) -> dict:
    study = store.add(Study(name="demo"))
    assay = store.add(Assay(study_id=study.id, name="kinetic"))
    gfp = store.add(Signal(name="GFP", kind="fluorescence"))
    od = store.add(Signal(name="OD", kind="biomass"))
    vector = store.add(Vector(name="v1"))
    chem = store.add(Chemical(name="aTc"))
    supp = store.add(Supplement(name="aTc-10", chemical_id=chem.id, concentration=10.0))
    sample = store.add(Sample(assay_id=assay.id, row=0, col=0, vector_id=vector.id, supplement_ids=[supp.id]))
    for t in range(4):
        store.add(Measurement(sample_id=sample.id, signal_id=gfp.id, value=10.0 * t, time=float(t)))
        store.add(Measurement(sample_id=sample.id, signal_id=od.id, value=0.1 * t, time=float(t)))
    return {"study": study.id, "gfp": gfp.id, "od": od.id, "chem": chem.id, "sample": sample.id}


def test_signal_kind_persists() -> None:
    store = PostgresStorage(_engine(), create=True)
    signal = store.add(Signal(name="GFP", kind="fluorescence"))
    assert store.get(Signal, signal.id).kind == "fluorescence"


def test_measurement_frame_join_and_concentrations() -> None:
    store = PostgresStorage(_engine(), create=True)
    ids = _seed_characterization(store)

    rows = list(store.measurement_frame(Selection(study_ids=[ids["study"]])))
    assert len(rows) == 8
    gfp_rows = [r for r in rows if r.signal_id == ids["gfp"]]
    assert all(r.signal == "GFP" and r.vector == "v1" and r.study_id == ids["study"] for r in gfp_rows)
    # The sample's supplement concentration is keyed by chemical id for dose-response.
    assert all(r.concentrations == {ids["chem"]: 10.0} for r in gfp_rows)
    # Streamed in (sample, signal, time) order.
    times = [r.time for r in gfp_rows]
    assert times == sorted(times)


def test_aggregate_measurements_pushdown() -> None:
    store = PostgresStorage(_engine(), create=True)
    ids = _seed_characterization(store)
    selection = Selection(study_ids=[ids["study"]], signal_ids=[ids["gfp"]])

    means = store.aggregate_measurements(func="mean", selection=selection)
    assert len(means) == 1 and abs(means[0].value - 15.0) < 1e-9  # mean(0,10,20,30)

    maxes = store.aggregate_measurements(func="max", selection=selection)
    assert len(maxes) == 1 and maxes[0].value == 30.0


def test_characterization_persistence_roundtrip() -> None:
    store = PostgresStorage(_engine(), create=True)
    ids = _seed_characterization(store)

    run = store.save_characterization(
        Characterization(analysis_type="Mean Expression", params_hash="abc123"),
        [
            CharacterizationDatum(
                characterization_id=0, sample_id=ids["sample"], signal_id=ids["gfp"], metric="Expression", value=15.0
            ),
            CharacterizationDatum(
                characterization_id=0, sample_id=ids["sample"], signal_id=ids["od"], metric="Expression", value=0.15
            ),
        ],
    )
    assert run.id is not None

    found = store.query_characterizations(params_hash="abc123")
    assert len(found) == 1 and found[0].id == run.id

    data = store.get_characterization_data(run.id)
    assert len(data) == 2 and all(d.characterization_id == run.id for d in data)


def test_characterization_owner_scoping() -> None:
    engine = _engine()
    PostgresStorage(engine, create=True)
    org_a = PostgresStorage(engine, owner="org-a")
    org_b = PostgresStorage(engine, owner="org-b")

    org_a.save_characterization(
        Characterization(analysis_type="Alpha", params_hash="h"),
        [CharacterizationDatum(characterization_id=0, sample_id=1, signal_id=1, metric="Alpha", value=1.0)],
    )
    assert len(org_a.query_characterizations()) == 1
    assert org_b.query_characterizations() == []
