from __future__ import annotations

import pytest
from a2a_helpers import SUPPLIERS
from terrasentry_a2a.client import Supplier
from terrasentry_a2a.intent import (
    Intent,
    match_suppliers,
    message_text,
    parse_intent,
    record_id_for_supplier,
)

PEOPLE = [Supplier.model_validate(item) for item in SUPPLIERS]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("screen REC-001", Intent("screen", record_id="REC-001")),
        ("please check sup-002", Intent("screen", supplier_id="SUP-002")),
        ("investigate SUP-001", Intent("investigate", supplier_id="SUP-001")),
        ("screen PT Sumber Sejahtera Sriwijaya", Intent("screen", name="PT Sumber Sejahtera Sriwijaya")),
        ("PT Agro Sejahtera Borneo", Intent("screen", name="PT Agro Sejahtera Borneo")),
        ("status run-1a2b3c4d5e6f", Intent("status", run_id="run-1a2b3c4d5e6f")),
        ("how is batch-aaaaaa111111:REC-001", Intent("status", run_id="batch-aaaaaa111111:REC-001")),
        ("hello", Intent("help")),
        ("What can you do?", Intent("help")),
        ("status", Intent("help")),
    ],
)
def test_parse_intent(text: str, expected: Intent) -> None:
    parsed = parse_intent(text)
    assert parsed.kind == expected.kind
    assert (parsed.record_id, parsed.supplier_id, parsed.run_id) == (
        expected.record_id,
        expected.supplier_id,
        expected.run_id,
    )
    if expected.name:
        assert parsed.name == expected.name


def test_message_text_accepts_plain_text_and_json() -> None:
    assert message_text("  screen SUP-001 ") == "screen SUP-001"
    assert message_text('{"user_request": "screen SUP-001", "x": 1}') == "screen SUP-001"
    assert message_text("[1, 2]") == "[1, 2]"


def test_unique_name_resolves_ignoring_legal_forms() -> None:
    assert [item.supplier_id for item in match_suppliers("sumber sejahtera sriwijaya", PEOPLE)] == ["SUP-001"]
    assert [item.supplier_id for item in match_suppliers("PT Agro Borneo Sejahtera", PEOPLE)] == ["SUP-002"]


def test_shared_trading_name_is_returned_for_disambiguation() -> None:
    # Both suppliers trade as "Kencana Hijau", so neither is a clear winner.
    matches = match_suppliers("Kencana Hijau", PEOPLE)
    assert {item.supplier_id for item in matches} == {"SUP-003", "SUP-004"}


def test_exact_legal_name_beats_a_longer_name_that_contains_it() -> None:
    assert [item.supplier_id for item in match_suppliers("PT Kencana Hijau Lestari", PEOPLE)] == ["SUP-004"]


def test_unknown_name_has_no_match() -> None:
    assert match_suppliers("Totally Different Corp", PEOPLE) == []
    assert match_suppliers("", PEOPLE) == []


def test_record_id_follows_the_supplier_suffix() -> None:
    assert record_id_for_supplier("SUP-001") == "REC-001"
    assert record_id_for_supplier("SUP-U-ab12") == "REC-U-ab12"
