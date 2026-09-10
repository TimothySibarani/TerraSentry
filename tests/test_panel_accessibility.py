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


# The four surfaces the workstation actually paints on, darkest to lightest.
SURFACES = ("#141311", "#1b1a17", "#211f1c", "#292724")
BAND_COLOURS = ("#68c98a", "#6b9ada", "#f0c451", "#f07f90", "#b3aea4")


def test_queue_items_are_real_buttons():
    """The strongest fix for keyboard access is not needing a fix.

    The old portfolio put a click handler on a bare <tr> and had to bolt on tabindex,
    role and key handlers to make it usable. The rail uses real <button> elements, which
    are focusable, activate on Enter and Space, and announce themselves -- all for free.
    Regressing to a div with onClick would silently undo that.
    """
    ws = (ROOT / "frontend" / "src" / "components" / "Workstation.jsx").read_text(encoding="utf-8")
    assert "<button" in ws and 'type="button"' in ws
    assert "aria-current" in ws, "the selected row must be announced, not just tinted"
    assert "aria-label" in ws
    assert 'aria-label="Work queue and supply base"' in ws, "the rail needs an accessible name"


def test_selection_stays_addressable():
    """Selecting a supplier must remain linkable and survive the Back button.

    The rail is persistent now, so selection is state rather than navigation -- which is
    exactly when an app quietly stops having URLs.
    """
    ws = (ROOT / "frontend" / "src" / "components" / "Workstation.jsx").read_text(encoding="utf-8")
    assert "pushState" in ws
    assert "popstate" in ws, "Back must move the selection, not leave the page"
    assert "URLSearchParams" in ws


def test_panel_keeps_every_accessibility_affordance():
    assert ":focus-visible" in FRONTEND
    assert "prefers-reduced-motion" in FRONTEND
    assert 'className="facts"' in FRONTEND, "evidence must read in words before JSON"


def test_astro_text_colours_meet_wcag_aa():
    """Measured on all four surfaces the palette actually paints on."""
    for colour in ("#ece9e2", "#a5a096", "#d9a441", *BAND_COLOURS):
        assert colour in FRONTEND, f"{colour} is not the palette the panel uses"
        worst = min(contrast(colour, bg) for bg in SURFACES)
        assert worst >= 4.5, f"{colour} is {worst:.2f}:1 at worst, needs 4.5"


def test_identifiers_are_monospaced():
    """An ID that renders in body text reads as prose. Real tools do not do that."""
    assert "--mono:" in FRONTEND
    for cls in (".qid", ".qscore", ".score", ".src"):
        assert cls in FRONTEND, f"{cls} lost its monospace treatment"


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


def test_blocked_carries_a_second_encoding():
    """BLOCKED is a low-chroma grey, which sits too close to the reds under deutan vision.

    The palette validator flagged exactly that pair, so BLOCKED is hatched wherever it is
    painted as a solid. Dropping the hatch would put it back to colour-alone against a
    colour it cannot be told apart from.
    """
    css = (ROOT / "frontend" / "src" / "styles" / "tokens.css").read_text(encoding="utf-8")
    assert "repeating-linear-gradient" in css
    for cls in (".dist .BLOCKED", ".cell.BLOCKED", ".chip.BLOCKED"):
        assert cls in css, f"{cls} lost its hatch"


def test_every_chart_ships_a_table():
    """A bar you can only read by pixel length is not evidence, and this is a compliance tool."""
    charts = (ROOT / "frontend" / "src" / "components" / "Charts.jsx").read_text(encoding="utf-8")
    assert charts.count('className="tbl"') >= 2, "each chart needs its own table view"
    assert charts.count("<table>") >= 2


def test_loss_and_fire_are_not_on_one_pair_of_axes():
    """Hectares and detections are different units.

    Putting them on a dual axis would assert a relationship the data does not state; they
    are aligned small multiples sharing a year axis instead.
    """
    overview = (ROOT / "frontend" / "src" / "components" / "Overview.jsx").read_text(encoding="utf-8")
    assert overview.count("<YearBars") == 2, "loss and fire must be two charts, not one"
    charts = (ROOT / "frontend" / "src" / "components" / "Charts.jsx").read_text(encoding="utf-8")
    assert "y2Scale" not in charts and "rightAxis" not in charts
