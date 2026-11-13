"""Guards for the responsive stylesheet.

Responsiveness used to be entirely JavaScript-driven: chat.js toggled
`.is-wide` / `.is-narrow` from a ResizeObserver and the CSS reacted to those
classes, so with JS disabled (or before hydration, or on agent.html which ships
no JS at all) a 288px fixed rail rendered on a phone.

These tests assert the viewport-breakpoint baseline stays in place. The
container-query layer is a deliberate progressive enhancement on top of it —
see the header comment in style.css — so we check that BOTH survive.
"""

import re
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
_CSS_PATH = _STATIC / "style.css"


@pytest.fixture(scope="module")
def css() -> str:
    return _CSS_PATH.read_text(encoding="utf-8")


def _width_queries(css: str) -> list[str]:
    """Every @media query that constrains on width."""
    return [
        q for q in re.findall(r"@media([^{]+)\{", css) if "width" in q
    ]


def test_stylesheet_has_width_based_breakpoints(css: str):
    # The regression this file exists to prevent: zero width breakpoints.
    assert _width_queries(css), (
        "style.css has no width-based @media query — responsiveness has "
        "regressed to being 100% JavaScript-dependent."
    )


def test_mobile_breakpoint_hides_the_rail(css: str):
    # The rail is a fixed 288px; on a 375px phone it must not render.
    assert re.search(r"@media\s*\(max-width:\s*900px\)", css), (
        "the 900px mobile breakpoint is missing"
    )
    # Inside some max-width block, .rail must be hidden without needing a class.
    blocks = re.findall(
        r"@media\s*\(max-width:[^)]*\)\s*\{(.*?)\n\}", css, re.DOTALL
    )
    assert any(
        re.search(r"(^|[^.\w-])\.rail\s*\{[^}]*display:\s*none", block)
        for block in blocks
    ), "no class-free `.rail { display: none }` inside a max-width media query"


def test_container_query_enhancement_is_preserved(css: str):
    # The ResizeObserver layer is deliberate (narrow iframe on a wide screen);
    # the media queries must not have replaced it.
    assert ".is-narrow .rail" in css, (
        "the .is-narrow container-width layer was removed — the widget can no "
        "longer adapt when embedded in a narrow container on a wide viewport"
    )
    assert ".is-wide .rail" in css, (
        "the media query must let an explicitly-wide container override it"
    )


def test_app_shell_uses_dynamic_viewport_height(css: str):
    # 100vh sits under the mobile URL bar and hides the composer.
    assert "100dvh" in css, "the app shell should size to the dynamic viewport"
    # …but older browsers still need a fallback ahead of it.
    assert re.search(r"height:\s*100vh", css), "missing 100vh fallback for dvh"


def test_muted_text_token_passes_contrast(css: str):
    # --grey-400 (#98A2B3) is ~2.6:1 on white and must not be used for text.
    assert "--text-muted" in css, "the accessible muted-text token is missing"
    for prop in ("card-note", "privacy-note", "ticket-time"):
        block = re.search(r"\." + prop + r"\s*\{[^}]*\}", css)
        assert block, f".{prop} rule not found"
        assert "--grey-400" not in block.group(0), (
            f".{prop} uses --grey-400, which fails WCAG AA on white"
        )


# Bold, short, high-contrast components where sub-12px is a deliberate call:
# uppercase pills and a numeral inside a 21px circle. Everything that reads as
# prose must be >= 12px.
_SMALL_TEXT_EXEMPT = {".badge", ".step-n", ".ticket-status"}


def test_prose_text_is_at_least_12px(css: str):
    """Sub-12px body text is unreadable and was flagged in the audit."""
    offenders = []
    for rule in re.finditer(r"([^{}]+)\{([^}]*)\}", css):
        selector = rule.group(1).strip().splitlines()[-1].strip()
        match = re.search(r"font-size:\s*([\d.]+)px", rule.group(2))
        if not match or float(match.group(1)) >= 12:
            continue
        if any(selector.startswith(ok) for ok in _SMALL_TEXT_EXEMPT):
            continue
        offenders.append(f"{selector} -> {match.group(1)}px")

    assert not offenders, f"prose text below 12px: {offenders}"
