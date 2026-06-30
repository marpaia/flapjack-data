# flapjack-data

[Flapjack](https://github.com/flapjacksynbio/flapjack_api) is an open-source tool for managing
and analyzing the data you get from characterizing genetic constructs in the lab. When you
engineer a cell and want to know how a promoter or circuit behaves, you grow the cells in a plate
reader and record time-series signals (fluorescence from a reporter protein, optical density for
growth) well by well over hours. Flapjack gives that data a shared structure, so a GFP time course
from one experiment means the same thing as one from another, and analyses like expression rate or
dose-response curves run the same way across all of them.

Flapjack ships as a whole stack: a Django API, a database, a web UI, and a Python client. If all
you want is the data model, that is a lot of infrastructure to take on, and it can collide with
data infrastructure you already run.

`flapjack-data` is just the model and a storage contract. It defines the same entities as Flapjack
as plain Python dataclasses, plus a small `Storage` interface you implement against whatever you
already have: an in-memory dict, Postgres/TimescaleDB, or a remote Flapjack API. The model travels
between tools even when the storage underneath them differs.

Five types carry the core of an experiment:

- `Study`: a group of related experiments.
- `Assay`: one run on one machine within a study.
- `Sample`: a single well on the plate, plus what was in it.
- `Signal`: a quantity you measure, such as GFP fluorescence or optical density.
- `Measurement`: one reading of one `Signal` in one `Sample` at one time point.

They nest into a spine, `Study` → `Assay` → `Sample` → `Measurement`, and every `Measurement`
records which `Signal` it came from. So a single fluorescence reading knows the well it came from,
the run that well belonged to, and the study that grouped the runs:

```python
from flapjack_data import Study, Assay, Sample, Signal, Measurement

study = Study(name="degradation tags")
assay = Assay(study_id=1, name="kinetic", machine="Clariostar")  # belongs to study 1
gfp = Signal(name="GFP", kind="fluorescence")
well = Sample(assay_id=1, row=0, col=0)                          # a well in assay 1
reading = Measurement(sample_id=1, signal_id=1, value=523.0, time=2.0)  # GFP in well 1 at t=2
```

Each entity is a plain dataclass that refers to the others by id. The ids are assigned by the
storage layer when an entity is added, so the literals above stand in for ids a store would hand
back. Around the spine sit the registry entities that describe what was in each well: the `Media`
it grew in, the `Strain` of cell, the `Vector` (the `Dna` constructs carried on a plasmid), and any
`Supplement`s (a `Chemical` at a concentration, such as an inducer). Those are what let an analysis
ask how expression changes with inducer concentration.

`flapjack-data` ships an `InMemoryStorage` (zero-dependency, for tests and notebooks) and an
optional `PostgresStorage` (`pip install "flapjack-data[postgres]"`) backed by SQLAlchemy, for
Postgres/TimescaleDB or any SQLAlchemy database. The optional analysis engine
(`pip install "flapjack-data[analysis]"`, numpy/scipy/pandas) computes the characterization
metrics Flapjack defines from the same model: expression rate, induction curves, and
growth/ratiometric metrics.

## Data Model

The entity graph mirrors Flapjack:

```mermaid
erDiagram
    Study ||--o{ Assay : has
    Assay ||--o{ Sample : has
    Sample ||--o{ Measurement : has
    Signal ||--o{ Measurement : labels
    Media ||--o{ Sample : in
    Strain ||--o{ Sample : in
    Vector ||--o{ Sample : in
    Chemical ||--o{ Supplement : basis
    Supplement }o--o{ Sample : "added to"
    Dna }o--o{ Vector : in
```

Every entity is a plain dataclass; relationships are by id; ids are assigned by the storage
layer when an entity is added.

| Entity                 | Key fields                                                                       |
| ---------------------- | -------------------------------------------------------------------------------- |
| `Study`                | `name`, `description`, `public`                                                  |
| `Assay`                | `study_id`, `name`, `machine`, `temperature`                                     |
| `Sample`               | `assay_id`, `row`, `col`, `media_id`, `strain_id`, `vector_id`, `supplement_ids` |
| `Signal`               | `name`, `description`, `color`, `kind`                                           |
| `Measurement`          | `sample_id`, `signal_id`, `value`, `time`                                        |
| `Media`, `Strain`      | `name`, `description`                                                            |
| `Chemical`             | `name`, `description`, `pubchemid`                                               |
| `Supplement`           | `name`, `chemical_id`, `concentration`                                           |
| `Dna`                  | `name`                                                                           |
| `Vector`               | `name`, `dna_ids`                                                                |
| `Characterization`     | `analysis_type`, `spec`, `params_hash`, `name`                                   |
| `CharacterizationDatum`| `characterization_id`, `sample_id`, `signal_id`, `metric`, `value`, `time`, `concentration`, `concentration2` |

`Signal.kind` is an optional role hint (`"fluorescence"`, `"biomass"`, `"od"`); the
biomass/reference role for a given analysis can still be chosen per request. `Characterization`
and `CharacterizationDatum` persist analysis runs and their results (see below).

## Storage Contract

`Storage` is the interface for persisting and querying the model. Implement it against any
backend (an in-memory dict, Postgres/TimescaleDB, or a remote Flapjack API) so the same
model plugs into different storage primitives.

```python
from typing import Protocol

class Storage(Protocol):
    def add(self, entity): ...
    def get(self, entity_type, entity_id): ...
    def list_all(self, entity_type): ...
    def query_measurements(self, *, study_id=None, assay_id=None,
                           sample_id=None, signal_id=None): ...
```

`CharacterizationStorage` extends `Storage` with the characterization read/write paths
(`measurement_frame`, `aggregate_measurements`, and the `save_/get_/query_characterization`
methods). Both `InMemoryStorage` and `PostgresStorage` implement it.

`InMemoryStorage` (used in the example above) is the zero-dependency reference implementation,
useful for tests and notebooks. `PostgresStorage` implements the same contract over SQLAlchemy,
optionally scoped to one `owner`:

```python
from flapjack_data import Study
from flapjack_data.backends.postgres import PostgresStorage

store = PostgresStorage("postgresql+psycopg://user:pass@localhost/flapjack", owner="org-123", create=True)
study = store.add(Study(name="degradation tags"))  # stamped with owner="org-123"
store.list_all(Study)  # only this owner's rows
```

### Migrations

`flapjack-data` ships its own Alembic migration chain so the schema can evolve over time. It
uses a dedicated version table (`flapjack_data_version`) and manages only its own tables, so it
runs alongside the migration chain of any application that embeds it without collision: two
independent chains, one database.

```sh
flapjack-data migrate --database-url postgresql+psycopg://user:pass@host/db
```

or programmatically:

```python
from flapjack_data.backends.postgres import migrations

migrations.upgrade("postgresql+psycopg://user:pass@host/db")
```

`PostgresStorage(..., create=True)` still calls `create_all` for throwaway databases (tests,
notebooks); use the migrations for anything you intend to evolve. Database-enforced tenancy
(e.g. row-level security on the `owner` column) is layered on by your application's own
migration.

## Characterization

Flapjack doesn't store characterization metrics; it recomputes them from raw measurements on
every request. `flapjack-data` reproduces that computation, and also lets you persist and cache
the results. An `AnalysisSpec` describes *what* to compute: a measurement `Selection`,
an `AnalysisType`, and its parameters (the per-request biomass/reference signals, the
dose-response analyte, and an inner `function` for induction/heatmap).

| Analysis type | Output |
| ------------- | ------ |
| `VELOCITY` | time-series d/dt of a signal (Savitzky-Golay) |
| `MEAN_VELOCITY`, `MAX_VELOCITY` | one aggregate per sample/signal |
| `EXPRESSION_RATE_INDIRECT` | time-series `d(signal)/dt ÷ biomass` |
| `EXPRESSION_RATE_DIRECT` | time-series rate (wellFARe one-step inverse problem) |
| `EXPRESSION_RATE_INVERSE` | time-series rate (Gaussian-basis inverse problem) |
| `MEAN_EXPRESSION`, `MAX_EXPRESSION` | one aggregate per sample/signal |
| `INDUCTION_CURVE`, `KYMOGRAPH` | inner `function` vs. inducer concentration |
| `HEATMAP` | inner `function` over two inducer concentrations |
| `ALPHA`, `RHO` | ratiometric expression (Gompertz growth-phase fit) |
| `BACKGROUND_CORRECT` | background-subtracted measurements |

The contract types (`AnalysisType`, `AnalysisSpec`, `Selection`) are dependency-free; the engine
that runs them needs the `[analysis]` extra (numpy/scipy/pandas):

```python
from flapjack_data import AnalysisSpec, AnalysisType, Selection
from flapjack_data.characterization import engine

spec = AnalysisSpec(
    type=AnalysisType.EXPRESSION_RATE_INDIRECT,
    selection=Selection(study_ids=[study.id], signal_ids=[gfp.id]),
    biomass_signal_id=od.id,
)
result = engine.run(spec, store, persist=True)   # compute and store the run
result.data                                       # list[CharacterizationDatum]

engine.run(spec, store)                           # same spec → served from cache by params hash
```

Results are keyed by a stable hash of the spec, so `run` returns a previously persisted run
instead of recomputing it.

### Scaling

The characterization read path is built to keep the (large) measurement table off the heap:

- `measurement_frame` streams rows from a server-side cursor and is the only path that spans the
  relational graph (measurement → sample → assay → study, plus the per-sample dose-response
  concentrations), so the engine never materializes the whole table.
- `aggregate_measurements` pushes `Mean`/`Max` down to the database as a `GROUP BY` rather than
  pulling every measurement into Python.
- Measurements carry a composite `(sample_id, signal_id, time)` index for the ordered
  per-sample reads the time-series analyses do, and results land in a dedicated
  `characterizationdatum` table indexed by run.
- For very large measurement volumes, `measurement` can be promoted to a TimescaleDB hypertable
  on `time` independently of this package.
