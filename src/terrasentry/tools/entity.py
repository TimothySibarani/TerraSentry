"""Corporate entity lookup and ownership-anomaly heuristics.

**The data behind this tool is synthetic.** Indonesia's company registry (AHU,
Kemenkumham) has a public search interface but no clean public API, so the demo
runs on a hand-built dataset in ``data/entities/suppliers.json`` that mirrors the
*shape* of real records.

Say this out loud on stage. Splitting real geospatial data from synthetic entity
data and naming which is which adds credibility -- pretending the registry feed is
live would not survive one informed question.

What is genuinely transferable is the heuristic layer below: these rules work
unchanged against a real registry feed the day one is available.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

Severity = Literal["info", "low", "medium", "high"]

DEFAULT_REGISTRY = Path("data/entities/suppliers.json")

# An entity incorporated shortly before it starts supplying is not proof of anything,
# but it is the single most common structural marker in documented nominee cases.
RECENT_INCORPORATION_MONTHS = 18


@dataclass
class EntityFinding:
    code: str
    severity: Severity
    statement: str
    artifact: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Entity:
    entity_id: str
    legal_name: str
    registration_number: str
    registered_address: str
    incorporated_on: str  # ISO date
    directors: list[str]
    shareholders: list[str]
    permit_numbers: list[str]
    parcels: list[str]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Entity":
        return cls(
            entity_id=raw["entity_id"],
            legal_name=raw["legal_name"],
            registration_number=raw.get("registration_number", ""),
            registered_address=raw.get("registered_address", ""),
            incorporated_on=raw.get("incorporated_on", ""),
            directors=list(raw.get("directors", [])),
            shareholders=list(raw.get("shareholders", [])),
            permit_numbers=list(raw.get("permit_numbers", [])),
            parcels=list(raw.get("parcels", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EntityRegistry:
    """In-memory registry over the synthetic dataset."""

    def __init__(self, path: str | Path = DEFAULT_REGISTRY) -> None:
        self.path = Path(path)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.source_label: str = payload.get("source_label", "SYNTHETIC entity registry")
        self.entities: list[Entity] = [Entity.from_dict(e) for e in payload["entities"]]
        self._by_id = {e.entity_id: e for e in self.entities}

    # -- lookup -----------------------------------------------------------

    def get(self, entity_id: str) -> Entity | None:
        return self._by_id.get(entity_id)

    def find_by_name(self, name: str) -> Entity | None:
        needle = _normalise(name)
        for e in self.entities:
            if _normalise(e.legal_name) == needle:
                return e
        # fall back to containment, which catches "PT Rimba Lestari" vs "PT Rimba Lestari Jaya"
        for e in self.entities:
            if needle in _normalise(e.legal_name) or _normalise(e.legal_name) in needle:
                return e
        return None

    def owner_of_parcel(self, parcel_id: str) -> Entity | None:
        return next((e for e in self.entities if parcel_id in e.parcels), None)

    # -- heuristics -------------------------------------------------------

    def analyse(self, entity: Entity, today: date | None = None) -> list[EntityFinding]:
        """Run every ownership-structure heuristic against one entity.

        Each finding is a *signal*, never a verdict. The scoring rubric weights them;
        a human reads them. None of these rules asserts wrongdoing on its own.
        """
        today = today or date.today()
        findings: list[EntityFinding] = []

        findings.extend(self._shared_address(entity))
        findings.extend(self._shared_directors(entity))
        f = self._recent_incorporation(entity, today)
        if f:
            findings.append(f)

        return findings

    def _shared_address(self, entity: Entity) -> list[EntityFinding]:
        if not entity.registered_address.strip():
            return []
        addr = _normalise(entity.registered_address)
        matches = [
            e for e in self.entities
            if e.entity_id != entity.entity_id and _normalise(e.registered_address) == addr
        ]
        if not matches:
            return []
        return [
            EntityFinding(
                code="SHARED_REGISTERED_ADDRESS",
                severity="high" if len(matches) >= 2 else "medium",
                statement=(
                    f"{entity.legal_name} shares its registered address with "
                    f"{len(matches)} other entit{'ies' if len(matches) > 1 else 'y'} in the registry."
                ),
                artifact={
                    "address": entity.registered_address,
                    "matched_entities": [
                        {"entity_id": e.entity_id, "legal_name": e.legal_name} for e in matches
                    ],
                },
            )
        ]

    def _shared_directors(self, entity: Entity) -> list[EntityFinding]:
        mine = {_normalise(d) for d in entity.directors}
        if not mine:
            return []
        out: list[EntityFinding] = []
        for other in self.entities:
            if other.entity_id == entity.entity_id:
                continue
            overlap = mine & {_normalise(d) for d in other.directors}
            if overlap:
                out.append(
                    EntityFinding(
                        code="SHARED_DIRECTORS",
                        severity="medium",
                        statement=(
                            f"{entity.legal_name} shares {len(overlap)} director(s) with "
                            f"{other.legal_name}."
                        ),
                        artifact={
                            "counterparty": {"entity_id": other.entity_id, "legal_name": other.legal_name},
                            "shared_directors": sorted(overlap),
                        },
                    )
                )
        return out

    def _recent_incorporation(self, entity: Entity, today: date) -> EntityFinding | None:
        if not entity.incorporated_on:
            return None
        try:
            inc = datetime.strptime(entity.incorporated_on, "%Y-%m-%d").date()
        except ValueError:
            return None
        months = (today.year - inc.year) * 12 + (today.month - inc.month)
        if months > RECENT_INCORPORATION_MONTHS:
            return None
        return EntityFinding(
            code="RECENT_INCORPORATION",
            severity="low" if months > 6 else "medium",
            statement=(
                f"{entity.legal_name} was incorporated {months} month(s) ago "
                f"({entity.incorporated_on}), shortly before entering the supply chain."
            ),
            artifact={"incorporated_on": entity.incorporated_on, "months_ago": months},
        )

    # -- the branch that makes the demo ------------------------------------

    def investigate_adjacent_parcel(self, parcel_id: str, supplier: Entity) -> list[EntityFinding]:
        """Called by the orchestrator when boundary loss makes ownership relevant.

        This is the unplanned step: nothing in the original due diligence plan says
        "look up the neighbour". The agent decides to run it only after change
        detection puts loss on a boundary it cannot attribute.
        """
        neighbour = self.owner_of_parcel(parcel_id)
        if neighbour is None:
            return [
                EntityFinding(
                    code="ADJACENT_PARCEL_UNKNOWN",
                    severity="low",
                    statement=f"No registered owner found for adjacent parcel {parcel_id}.",
                    artifact={"parcel_id": parcel_id},
                )
            ]

        findings = [
            EntityFinding(
                code="ADJACENT_PARCEL_OWNER",
                severity="info",
                statement=f"Adjacent parcel {parcel_id} is registered to {neighbour.legal_name}.",
                artifact={"parcel_id": parcel_id, "owner": neighbour.to_dict()},
            )
        ]

        if _normalise(neighbour.registered_address) == _normalise(supplier.registered_address):
            findings.append(
                EntityFinding(
                    code="ADJACENT_OWNER_SAME_ADDRESS",
                    severity="high",
                    statement=(
                        f"The owner of adjacent parcel {parcel_id} ({neighbour.legal_name}) is "
                        f"registered at the same address as the supplier under assessment."
                    ),
                    artifact={
                        "parcel_id": parcel_id,
                        "shared_address": neighbour.registered_address,
                        "supplier": supplier.legal_name,
                        "neighbour": neighbour.legal_name,
                    },
                )
            )

        findings.extend(self.analyse(neighbour))
        return findings


def _normalise(value: str) -> str:
    return " ".join(value.lower().replace(",", " ").replace(".", " ").split())
