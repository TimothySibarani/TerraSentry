"""A claim without an artifact is an opinion."""

from terrasentry.evidence import EvidenceLedger


def test_ledger_records_and_ids_claims():
    ledger = EvidenceLedger("PT Demo")
    ev = ledger.add(claim="38.2 ha lost", source="Hansen GFC", artifact={"loss_ha": 38.2})
    assert len(ledger) == 1
    assert ledger.get(ev.claim_id) is ev
    assert ev.claim_id.startswith("ev_")


def test_claim_ids_are_stable():
    a = EvidenceLedger("x").add(claim="same", source="src", artifact={"a": 1})
    b = EvidenceLedger("y").add(claim="same", source="src", artifact={"a": 2})
    assert a.claim_id == b.claim_id


def test_verify_flags_empty_artifact():
    ledger = EvidenceLedger("PT Demo")
    ledger.add(claim="trust me", source="vibes", artifact={})
    problems = ledger.verify()
    assert any("no supporting artifact" in p for p in problems)
