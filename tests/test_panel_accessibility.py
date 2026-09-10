"""Static guards on the panel markup.

These are cheap insurance, not a substitute for testing with a keyboard. They exist
because every one of them was actually broken at some point: rows that only responded to
a mouse, colours that failed contrast, and motion with no reduced-motion escape.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

# The Astro panel is the primary UI; web/index.html is kept as a no-build fallback.
# Both must carry the same affordances, so the guards run over both.
FRONTEND = chr(10).join(
    p.read_text(encoding="utf-8")
    for p in sorted((ROOT / "frontend" / "src").rglob("*"))
    if p.suffix in {".jsx", ".astro", ".css", ".js"}
)


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


def test_astro_panel_keeps_every_accessibility_affordance():
    """A rewrite is exactly when hard-won accessibility work gets quietly dropped."""
    assert "tabIndex={0}" in FRONTEND, "portfolio rows must be reachable by tab"
    assert 'role="button"' in FRONTEND
    assert "aria-label" in FRONTEND
    assert '"Enter"' in FRONTEND and '" "' in FRONTEND
    assert ":focus-visible" in FRONTEND
    assert "prefers-reduced-motion" in FRONTEND
    assert "tablewrap" in FRONTEND
    assert 'className="facts"' in FRONTEND, "evidence must read in words before JSON"


# Light-theme surfaces the panel actually paints on.
SURFACES = ("#ffffff", "#f8f8f5", "#f2f2ee", "#fcfcfa")
BAND_COLOURS = ("#136c3c", "#15537f", "#8a5300", "#b02219", "#7a1712")


def test_astro_text_colours_meet_wcag_aa():
    """Text must clear 4.5:1 on every surface it can land on, not just the best one."""
    for colour in ("#191916", "#63635b", "#0f5c38", *BAND_COLOURS):
        assert colour in FRONTEND, f"{colour} is not the palette the panel uses"
        worst = min(contrast(colour, bg) for bg in SURFACES)
        assert worst >= 4.5, f"{colour} is {worst:.2f}:1 at worst, needs 4.5"


def test_band_markers_are_legible_in_reverse():
    """Pills and the distribution bar put white text on the band colour."""
    for colour in BAND_COLOURS:
        ratio = contrast("#ffffff", colour)
        assert ratio >= 4.5, f"white on {colour} is {ratio:.2f}:1"


def test_colour_is_reserved_for_meaning():
    """Grey carries the interface; colour means risk. If everything is coloured, nothing is."""
    assert "--go:" in FRONTEND and "--nogo:" in FRONTEND
    for generic in ("#3ddc97", "#f0b429", "#6ba7d8"):
        assert generic not in FRONTEND, f"{generic} is the generic dashboard accent, not a risk band"


def test_identifiers_are_monospaced():
    """An ID that renders in body text reads as prose. Real tools do not do that."""
    assert "--mono:" in FRONTEND
    for cls in (".sid", ".score", "td.num", ".src"):
        assert cls in FRONTEND


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


def test_no_component_references_an_undefined_css_variable():
    """A dangling var() does not error. It just silently stops working.

    Renaming the palette is exactly when this happens: the stylesheet moves on and the
    components keep asking for tokens that no longer exist.
    """
    import re

    css = (ROOT / "frontend" / "src" / "styles" / "tokens.css").read_text(encoding="utf-8")
    defined = set(re.findall(r"^\s*(--[a-z-]+):", css, re.M))

    used = set()
    for path in (ROOT / "frontend" / "src").rglob("*"):
        if path.suffix in {".jsx", ".astro", ".css"}:
            used |= set(re.findall(r"var\((--[a-z-]+)\)", path.read_text(encoding="utf-8")))

    dangling = sorted(used - defined)
    assert not dangling, f"components reference undefined tokens: {dangling}"


def test_components_use_tokens_not_raw_hex():
    """Raw hex in a component is how a palette drifts out of sync with itself."""
    import re

    offenders = []
    for path in (ROOT / "frontend" / "src").rglob("*"):
        if path.suffix != ".jsx":
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in re.findall(r"#[0-9a-fA-F]{6}", line):
                # White is a genuine primitive here: SVG halos and reversed text.
                if match.lower() not in {"#ffffff", "#fff"}:
                    offenders.append(f"{path.name}:{n} {match}")
    assert not offenders, f"raw hex outside the palette: {offenders}"
