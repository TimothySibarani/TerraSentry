"""Deterministic request parsing and supplier-name matching; no model is involved."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from terrasentry_a2a.client import Supplier

IntentKind = Literal["screen", "investigate", "status", "help"]

_RECORD = re.compile(r"\bREC-[A-Z0-9-]+\b", re.IGNORECASE)
_SUPPLIER = re.compile(r"\bSUP-[A-Z0-9-]+\b", re.IGNORECASE)
_RUN = re.compile(r"\b(?:run|batch)-[0-9a-f]{6,}(?::REC-[A-Z0-9-]+)?", re.IGNORECASE)
_GREETING = re.compile(r"^\s*(hi|hello|hey|help|what can you do)\b[\s!?.]*$", re.IGNORECASE)
_INVESTIGATE = re.compile(r"\b(investigate|deep|agent|full analysis|analy[sz]e)\b", re.IGNORECASE)
_STATUS = re.compile(r"\b(status|progress|update on|how is|how's)\b", re.IGNORECASE)
_SCREEN = re.compile(r"\b(screen|screening|check|assess|risk)\b", re.IGNORECASE)
_FILLER = re.compile(
    r"\b(please|can you|could you|run|a|an|the|for|on|of|supplier|company|investigate|deep|agent|full|"
    r"analy[sz]e|analysis|screen|screening|check|assess|risk|status|progress|update|how is|how's)\b",
    re.IGNORECASE,
)
_LEGAL_FORMS = re.compile(r"\b(pt|cv|tbk|ltd|sdn|bhd|inc|llc|co)\b")
_CLEAR_MARGIN = 0.1
_CUTOFF = 0.62


@dataclass(frozen=True)
class Intent:
    kind: IntentKind
    record_id: str | None = None
    supplier_id: str | None = None
    run_id: str | None = None
    name: str | None = None


def message_text(raw: str) -> str:
    """Joule may send plain text or a JSON object; return the user's words."""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw.strip()
    if isinstance(parsed, dict):
        for key in ("user_request", "query", "text", "message"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return raw.strip()


def parse_intent(text: str) -> Intent:
    if _GREETING.match(text):
        return Intent("help")
    run = _RUN.search(text)
    rest = _RUN.sub(" ", text)  # a child run id embeds a record id; it is not a separate target
    record = _RECORD.search(rest)
    supplier = _SUPPLIER.search(rest)
    name = " ".join(_FILLER.sub(" ", _SUPPLIER.sub(" ", _RECORD.sub(" ", rest))).split())
    name = name.strip(" ,.:;?!\"'") or None
    ids = {
        "record_id": record.group(0).upper() if record else None,
        "supplier_id": supplier.group(0).upper() if supplier else None,
        "run_id": run.group(0) if run else None,
    }
    if ids["run_id"] and (_STATUS.search(text) or not (record or supplier or name)):
        return Intent("status", **ids)
    has_target = bool(record or supplier or name)
    if _INVESTIGATE.search(text) and has_target:
        return Intent("investigate", name=name, **ids)
    if has_target and (_SCREEN.search(text) or not _STATUS.search(text)):
        return Intent("screen", name=name, **ids)
    return Intent("help")


def _normal(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", value.lower())
    return " ".join(_LEGAL_FORMS.sub(" ", cleaned).split())


def match_suppliers(query: str, suppliers: list[Supplier], *, limit: int = 3) -> list[Supplier]:
    """Rank suppliers by name similarity; a clear winner comes back alone, otherwise the candidates."""
    wanted = _normal(query)
    if not wanted:
        return []
    scored: list[tuple[float, Supplier]] = []
    for supplier in suppliers:
        best = 0.0
        for name in (supplier.legal_name, supplier.trading_name):
            candidate = _normal(name)
            if not candidate:
                continue
            ratio = 1.0 if candidate == wanted else SequenceMatcher(None, wanted, candidate).ratio()
            if wanted in candidate or candidate in wanted:
                ratio = max(ratio, 0.9)
            best = max(best, ratio)
        if best >= _CUTOFF:
            scored.append((best, supplier))
    scored.sort(key=lambda item: (-item[0], item[1].supplier_id))
    if not scored:
        return []
    top, runner_up = scored[0][0], scored[1][0] if len(scored) > 1 else 0.0
    if top == 1.0 and runner_up < 1.0:
        return [scored[0][1]]
    if top - runner_up >= _CLEAR_MARGIN and top >= 0.85:
        return [scored[0][1]]
    return [supplier for _, supplier in scored[:limit]]


def record_id_for_supplier(supplier_id: str) -> str:
    """Seed and submitted records share their numeric suffix with the supplier (SUP-001 -> REC-001)."""
    return "REC-" + supplier_id.removeprefix("SUP-")


__all__ = ["Intent", "match_suppliers", "message_text", "parse_intent", "record_id_for_supplier"]
