"""The pipeline must report work time, not display pacing."""

import time

from terrasentry import pipeline


def test_elapsed_excludes_consumer_time():
    """A slow consumer must not inflate elapsed_ms -- the panel paces by sleeping here."""
    slow = []

    def on_step(step):
        slow.append(step)
        time.sleep(0.05)

    result = pipeline.run("SUP-001", on_step=on_step)
    steps = result["steps"]

    assert len(steps) == len(slow)
    # 10 steps x 50 ms of pacing = ~500 ms of sleeping that must NOT be counted.
    assert steps[-1]["elapsed_ms"] < 200, f"pacing leaked into elapsed_ms: {steps[-1]['elapsed_ms']}"
    assert [s["elapsed_ms"] for s in steps] == sorted(s["elapsed_ms"] for s in steps)


def test_broken_consumer_does_not_break_the_run():
    def exploding(step):
        raise RuntimeError("consumer is broken")

    result = pipeline.run("SUP-001", on_step=exploding)
    assert result["assessment"]["recommendation"] == "ESCALATE"


def test_branch_fires_only_when_boundary_loss_is_material():
    flagged = pipeline.run("SUP-001")
    clean = pipeline.run("SUP-002")
    assert flagged["adjacent_parcel_branch_taken"] is True
    assert clean["adjacent_parcel_branch_taken"] is False
    assert any(s["phase"] == "branch" for s in flagged["steps"])
    assert not any(s["phase"] == "branch" for s in clean["steps"])


def test_cli_and_panel_share_one_code_path():
    """Both entrypoints call pipeline.run, so a plain run and a streamed run must agree."""
    plain = pipeline.run("SUP-001")
    streamed = pipeline.run("SUP-001", on_step=lambda s: None)
    assert plain["assessment"] == streamed["assessment"]
    assert plain["dds"]["gaps"] == streamed["dds"]["gaps"]


def test_blocked_result_has_the_same_shape_as_a_completed_one():
    """A blocked run must not omit keys.

    The panel checked `if (r.map)` and friends; when a blocked run omitted them it left
    its placeholders up, so a finished screening looked like a hung request. Consumers
    should never have to guess which keys exist.
    """
    ok = pipeline.run("SUP-002")
    blocked = pipeline.run("SUP-023")

    assert blocked["blocked"] is True
    assert ok["blocked"] is False

    contract = {"blocked", "supplier", "supplier_id", "geometry", "map", "assessment",
                "dds", "evidence", "evidence_count", "steps", "adjacent_parcel_branch_taken"}
    assert contract <= set(ok)
    assert contract <= set(blocked)


def test_blocked_run_still_explains_itself():
    r = pipeline.run("SUP-023")
    assert r["problems"], "a blocked run must say what is wrong"
    assert r["required_action"], "a blocked run must say what to do about it"
    assert r["evidence_count"] >= 1, "the geometry finding is itself evidence"
    assert r["assessment"] is None and r["dds"] is None
