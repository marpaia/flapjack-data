"""flapjack-data: the Flapjack measurement data model as a dependency-free package.

Provides the domain types (study/assay/sample/measurement and the surrounding registry
entities), a small ``Storage`` contract for persisting and querying them, and an in-memory
reference backend. Parsers, calibration, analysis, and database backends depend on this
model and live in their own packages or applications.
"""

from flapjack_data.backends.memory import InMemoryStorage
from flapjack_data.model import (
    Assay,
    Chemical,
    Dna,
    Measurement,
    Media,
    Sample,
    Signal,
    Strain,
    Study,
    Supplement,
    Vector,
)
from flapjack_data.storage import Storage

__all__ = [
    "Study",
    "Assay",
    "Media",
    "Strain",
    "Chemical",
    "Supplement",
    "Dna",
    "Vector",
    "Signal",
    "Sample",
    "Measurement",
    "Storage",
    "InMemoryStorage",
]
