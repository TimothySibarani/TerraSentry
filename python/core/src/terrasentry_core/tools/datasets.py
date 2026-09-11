"""Deterministic lookups over the committed seed datasets.

The agent tools and the assessment harness both address records by id
(``record_id``, ``polygon_id``, ``supplier_id``); the model never supplies data
values. This module is the only place that maps ids to seed data, so the
synthetic-legality disclosure travels with every lookup.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from terrasentry_core.errors import SeedLookupError
from terrasentry_core.seed.schemas import (
    BatchDataset,
    BatchRecord,
    OperatorDataset,
    OperatorRecord,
)

DEFAULT_BATCH_PATH = Path("data/seed/batch_50.json")
DEFAULT_OPERATOR_PATH = Path("data/seed/operator.json")


class SeedDatasets:
    """In-memory lookup over one seed batch plus the synthetic EU operator."""

    def __init__(self, batch: BatchDataset, operator: OperatorRecord) -> None:
        self._batch = batch
        self._operator = operator
        self._by_record = {record.record_id: record for record in batch.records}
        self._by_polygon = {record.polygon.id: record for record in batch.records}
        self._by_supplier = {record.legality.supplier_id: record for record in batch.records}
        self._by_scenario = {
            record.polygon.scenario: record
            for record in batch.records
            if record.polygon.scenario is not None
        }

    @classmethod
    def load(
        cls,
        *,
        batch_path: Path = DEFAULT_BATCH_PATH,
        operator_path: Path = DEFAULT_OPERATOR_PATH,
    ) -> SeedDatasets:
        batch = BatchDataset.model_validate_json(batch_path.read_text(encoding="utf-8"))
        operator = OperatorDataset.model_validate_json(
            operator_path.read_text(encoding="utf-8")
        ).operator
        return cls(batch, operator)

    @property
    def batch(self) -> BatchDataset:
        return self._batch

    @property
    def operator(self) -> OperatorRecord:
        return self._operator

    @property
    def records(self) -> list[BatchRecord]:
        return list(self._batch.records)

    @property
    def disclosures(self) -> list[str]:
        return sorted(
            {
                self._batch.disclosure,
                self._operator.disclosure,
                *(record.legality.disclosure for record in self._batch.records),
                *(record.consignment.disclosure for record in self._batch.records),
            }
        )

    def get_record(self, record_id: str) -> BatchRecord:
        try:
            return self._by_record[record_id]
        except KeyError as exc:
            raise SeedLookupError("record", record_id) from exc

    def record_for_polygon(self, polygon_id: str) -> BatchRecord:
        try:
            return self._by_polygon[polygon_id]
        except KeyError as exc:
            raise SeedLookupError("polygon", polygon_id) from exc

    def record_for_supplier(self, supplier_id: str) -> BatchRecord:
        try:
            return self._by_supplier[supplier_id]
        except KeyError as exc:
            raise SeedLookupError("supplier", supplier_id) from exc

    def record_for_scenario(self, scenario: str) -> BatchRecord:
        try:
            return self._by_scenario[scenario]
        except KeyError as exc:
            raise SeedLookupError("scenario", scenario) from exc

    def scenarios(self) -> list[str]:
        return sorted(self._by_scenario)

    def record_ids(self) -> Iterable[str]:
        return self._by_record.keys()


__all__ = ["DEFAULT_BATCH_PATH", "DEFAULT_OPERATOR_PATH", "SeedDatasets"]
