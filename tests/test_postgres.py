from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from flapjack_data import Assay, Measurement, Sample, Signal, Study
from flapjack_data.backends.postgres import PostgresStorage


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
