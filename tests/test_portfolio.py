"""Portfolio screening: the aggregate view a mill actually works from."""

from terrasentry import portfolio


def _p():
    return portfolio.screen_all()


def test_every_supplier_is_screened_and_banded():
    p = _p()
    assert p["totals"]["suppliers"] == len(p["rows"])
    assert sum(p["bands"].values()) == p["totals"]["suppliers"]
    assert all(r["band"] in portfolio.BAND_ORDER for r in p["rows"])


def test_the_rubric_discriminates():
    """A screener that flags everything is as useless as one that flags nothing."""
    bands = _p()["bands"]
    assert bands["GO"] > 0, "nothing passed -- rubric is too harsh or the data is wrong"
    assert bands["GO"] < sum(bands.values()), "everything passed -- rubric is not discriminating"
    assert len([b for b, n in bands.items() if n]) >= 3, "demo should span at least three bands"


def test_exception_queue_is_worst_first_and_excludes_conditional():
    p = _p()
    severity = [portfolio._SEVERITY[r["band"]] for r in p["exceptions"]]
    assert severity == sorted(severity, reverse=True)
    assert all(r["band"] in portfolio.EXCEPTION_BANDS for r in p["exceptions"])
    assert not any(r["band"] == "CONDITIONAL" for r in p["exceptions"])


def test_every_exception_carries_a_reason_and_an_action():
    """A queue row a human cannot act on is noise."""
    for r in _p()["exceptions"]:
        assert r["reason"] and r["reason"] != "No findings"
        assert r["action"] and r["action"] != "None"


def test_smallholders_under_four_hectares_take_the_point_rule():
    p = _p()
    assert p["totals"]["point_rule_plots"] > 0, "demo has no sub-4 ha plot -- the hard real case"
    for r in p["rows"]:
        if r["area_ha"] is not None and r["geolocation_requirement"] is not None:
            expected = "polygon" if r["area_ha"] >= 4.0 else "point"
            assert r["geolocation_requirement"] == expected, r["supplier_id"]


def test_groups_cover_every_supplier_exactly_once():
    p = _p()
    grouped = [s["supplier_id"] for g in p["groups"] for s in g["suppliers"]]
    assert sorted(grouped) == sorted(r["supplier_id"] for r in p["rows"])
    assert len(grouped) == len(set(grouped))


def test_only_issuable_volume_counts_as_covered():
    """Conditional volume is not covered -- the statement cannot be issued yet."""
    p = _p()
    go_volume = sum(r["volume_m3_month"] for r in p["rows"] if r["band"] == "GO")
    total = sum(r["volume_m3_month"] for r in p["rows"])
    assert p["totals"]["volume_covered_pct"] == round(go_volume / total * 100, 1)
    assert p["totals"]["volume_covered_pct"] < 100
