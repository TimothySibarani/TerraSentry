"""The pipeline must report work time, not display pacing."""

import time

from rimba import pipeline


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
