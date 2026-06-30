from flapjack_data import (
    Assay,
    InMemoryStorage,
    Measurement,
    Sample,
    Signal,
    Study,
)


def _seed() -> tuple[InMemoryStorage, dict[str, int]]:
    store = InMemoryStorage()
    study = store.add(Study(name="degradation tags"))
    assay = store.add(Assay(study_id=study.id, name="kinetic", machine="Clariostar"))
    gfp = store.add(Signal(name="GFP"))
    od = store.add(Signal(name="OD"))
    sample = store.add(Sample(assay_id=assay.id, row=0, col=0))
    for t in range(3):
        store.add(Measurement(sample_id=sample.id, signal_id=gfp.id, value=10.0 * t, time=float(t)))
        store.add(Measurement(sample_id=sample.id, signal_id=od.id, value=0.1 * t, time=float(t)))
    return store, {"study": study.id, "assay": assay.id, "gfp": gfp.id, "od": od.id, "sample": sample.id}


def test_add_assigns_sequential_ids() -> None:
    store = InMemoryStorage()
    a = store.add(Study(name="a"))
    b = store.add(Study(name="b"))
    assert a.id == 1 and b.id == 2
    assert store.get(Study, 1).name == "a"
    assert {s.name for s in store.list_all(Study)} == {"a", "b"}


def test_query_measurements_by_signal_and_assay() -> None:
    store, ids = _seed()
    gfp = store.query_measurements(signal_id=ids["gfp"])
    assert len(gfp) == 3 and all(m.signal_id == ids["gfp"] for m in gfp)

    by_study = store.query_measurements(study_id=ids["study"])
    assert len(by_study) == 6

    by_assay_signal = store.query_measurements(assay_id=ids["assay"], signal_id=ids["od"])
    assert len(by_assay_signal) == 3


def test_query_measurements_unknown_study_is_empty() -> None:
    store, _ = _seed()
    assert store.query_measurements(study_id=999) == []
