"""Evidence ledger.

Every claim that enters a supplier dossier passes through here. A claim without a
traceable artifact is not a finding -- it is an opinion, and the Verifier step drops it.

This module is deliberately dumb: no network, no model calls, no scoring. It only
records what was observed, where it came from, and when.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Iterator


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Evidence:
    """A single traceable observation.

    Attributes:
        claim: Human-readable statement, e.g. "38.2 ha of tree cover lost since 2021".
        source: Named provenance, e.g. "NASA FIRMS VIIRS_SNPP_SP" or "Hansen GFC v1.11".
        artifact: The raw payload the claim was derived from. Must be JSON-serialisable
            and specific enough that a third party could re-derive the claim from it
            (hotspot IDs, pixel counts, permit numbers -- not prose summaries).
        retrieved_at: ISO-8601 UTC timestamp of retrieval.
        url: Public URL for the source, when one exists.
    """

    claim: str
    source: str
    artifact: dict[str, Any]
    retrieved_at: str = field(default_factory=_utcnow)
    url: str | None = None

    @property
    def claim_id(self) -> str:
        """Stable short id derived from claim + source, for citation markers."""
        digest = hashlib.sha256(f"{self.source}|{self.claim}".encode()).hexdigest()
        return f"ev_{digest[:10]}"

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["claim_id"] = self.claim_id
        return out


class EvidenceLedger:
    """Append-only collection of Evidence for one screening run."""

    def __init__(self, supplier: str) -> None:
        self.supplier = supplier
        self.opened_at = _utcnow()
        self._items: list[Evidence] = []

    def add(
        self,
        claim: str,
        source: str,
        artifact: dict[str, Any],
        url: str | None = None,
    ) -> Evidence:
        ev = Evidence(claim=claim, source=source, artifact=artifact, url=url)
        self._items.append(ev)
        return ev

    def __iter__(self) -> Iterator[Evidence]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def by_source(self, source_prefix: str) -> list[Evidence]:
        return [e for e in self._items if e.source.startswith(source_prefix)]

    def get(self, claim_id: str) -> Evidence | None:
        return next((e for e in self._items if e.claim_id == claim_id), None)

    # -- Verifier support -------------------------------------------------

    def verify(self) -> list[str]:
        """Return problems that must be resolved before the dossier can be issued.

        This is the mechanical half of the Verifier agent. The model-driven half
        (does the prose actually match the artifact?) lives in agent/orchestrator.py.
        """
        problems: list[str] = []
        for ev in self._items:
            if not ev.artifact:
                problems.append(f"{ev.claim_id}: claim has no supporting artifact")
            if not ev.source.strip():
                problems.append(f"{ev.claim_id}: claim has no named source")
            try:
                json.dumps(ev.artifact)
            except (TypeError, ValueError):
                problems.append(f"{ev.claim_id}: artifact is not JSON-serialisable")
        return problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "supplier": self.supplier,
            "opened_at": self.opened_at,
            "evidence_count": len(self._items),
            "evidence": [e.to_dict() for e in self._items],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
