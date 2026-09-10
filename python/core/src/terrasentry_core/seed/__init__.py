"""Deterministic synthetic seed data for the demo and the 50-record batch."""

from __future__ import annotations

from terrasentry_core.seed.generator import (
    BATCH_DISTRIBUTION,
    DEFAULT_RNG_SEED,
    demo_dataset,
    generate_batch,
    legality_dataset,
    operator_dataset,
)
from terrasentry_core.seed.schemas import (
    BatchDataset,
    BatchRecord,
    ConsignmentRecord,
    LegalityDataset,
    LegalityRecord,
    OperatorDataset,
    OperatorRecord,
    SeedDataset,
    SeedPolygon,
)

__all__ = [
    "BATCH_DISTRIBUTION",
    "DEFAULT_RNG_SEED",
    "BatchDataset",
    "BatchRecord",
    "ConsignmentRecord",
    "LegalityDataset",
    "LegalityRecord",
    "OperatorDataset",
    "OperatorRecord",
    "SeedDataset",
    "SeedPolygon",
    "demo_dataset",
    "generate_batch",
    "legality_dataset",
    "operator_dataset",
]
