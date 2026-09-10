"""Ownership heuristics: signals, never verdicts."""

from rimba.tools.entity import EntityRegistry


def _registry() -> EntityRegistry:
    return EntityRegistry("data/entities/suppliers.json")


def test_shared_address_is_detected():
    reg = _registry()
    supplier = reg.find_by_name("PT Rimba Lestari Jaya")
    codes = {f.code for f in reg.analyse(supplier)}
    assert "SHARED_REGISTERED_ADDRESS" in codes


def test_shared_directors_are_detected():
    reg = _registry()
    supplier = reg.find_by_name("PT Rimba Lestari Jaya")
    codes = {f.code for f in reg.analyse(supplier)}
    assert "SHARED_DIRECTORS" in codes


def test_clean_supplier_has_no_findings():
    reg = _registry()
    supplier = reg.find_by_name("PT Hijau Nusantara Mandiri")
    assert reg.analyse(supplier) == []


def test_adjacent_parcel_branch_surfaces_shared_address():
    reg = _registry()
    supplier = reg.find_by_name("PT Rimba Lestari Jaya")
    findings = reg.investigate_adjacent_parcel("PARCEL-N-114", supplier)
    codes = {f.code for f in findings}
    assert "ADJACENT_OWNER_SAME_ADDRESS" in codes


def test_unknown_parcel_is_reported_not_raised():
    reg = _registry()
    supplier = reg.find_by_name("PT Rimba Lestari Jaya")
    findings = reg.investigate_adjacent_parcel("PARCEL-DOES-NOT-EXIST", supplier)
    assert findings[0].code == "ADJACENT_PARCEL_UNKNOWN"
