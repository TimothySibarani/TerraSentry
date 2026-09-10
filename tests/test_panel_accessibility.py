"""Static guards on the panel markup.

These are cheap insurance, not a substitute for testing with a keyboard. They exist
because every one of them was actually broken at some point: rows that only responded to
a mouse, colours that failed contrast, and motion with no reduced-motion escape.
"""

from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")


def _lin(c):
    c = c / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _lum(hexcolor):
    h = hexcolor.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(fg, bg):
    a, b = _lum(fg), _lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


PANEL = "#16201c"


def test_rows_are_keyboard_operable():
    """A table row with only a click handler does not exist for keyboard users."""
    assert 'tabindex="0"' in HTML
    assert 'role="button"' in HTML
    assert 'aria-label=' in HTML
    assert '"Enter"' in HTML and '" "' in HTML, "Enter and Space must both activate a role=button"


def test_focus_is_visible_and_not_hidden_by_the_sticky_header():
    assert ":focus-visible" in HTML
    assert "outline:" in HTML.replace("outline: ", "outline:")
    assert "scroll-margin-top" in HTML, "sticky header would cover the focused row"


def test_reduced_motion_is_respected():
    assert "prefers-reduced-motion" in HTML


def test_wide_tables_scroll_inside_their_own_box():
    assert "tablewrap" in HTML
    assert "overflow-x: auto" in HTML


def test_evidence_shows_words_before_json():
    """Raw JSON is right for an auditor and wrong on a projector."""
    assert 'class="facts"' in HTML
    assert 'details class="raw"' in HTML


def test_text_colours_meet_wcag_aa():
    """Measured, not eyeballed. Both of these failed before: 3.58 and 4.27."""
    for name, colour in (("step meta", "#7b9789"), ("destructive", "#f26a6e"), ("muted", "#8ba396")):
        ratio = contrast(colour, PANEL)
        assert ratio >= 4.5, f"{name} {colour} is {ratio:.2f}:1 on {PANEL}, needs 4.5"
        assert colour in HTML, f"{name} colour {colour} is not the one the panel uses"


def test_no_emoji_used_as_an_icon():
    """Emoji render differently per platform and carry no accessible name."""
    for ch in "🌲🔥📊✅❌⚠️🚀":
        assert ch not in HTML
