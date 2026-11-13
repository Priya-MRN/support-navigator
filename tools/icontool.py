"""Generate the UI's lucide icon sprite from the packaged lucide icon set.

The rule this tool exists to enforce: **use only standard packaged icon sets;
never hand-author SVG path data.** ``web/templates/_icons.html`` used to be a
hand-transcription of lucide paths typed into the template, which is exactly the
kind of drift-prone copy this forbids. It is now GENERATED from the ``lucide``
PyPI package (pinned in requirements.txt), which bundles the unmodified upstream
lucide SVG files.

Which icons get generated is *discovered from actual usage*, never hand-listed,
so the sprite cannot drift away from the UI. Three call sites are scanned:

1. ``web/templates/*.html``  - literal ``<use href="#i-name">`` references.
2. ``web/static/chat.js``    - ``icon("name")`` helper calls.
3. ``knowledge_base.json``   - the ``"lucide"`` field on each topic, which
   chat.html renders dynamically via ``#i-{{ t.lucide }}``, plus the
   ``|default(...)`` fallback used in that same expression.

Usage::

    python tools/icontool.py            # regenerate the sprite
    python tools/icontool.py check      # verify it is up to date (exit 1 if not)
    python tools/icontool.py list       # show discovered icon ids and sources

Run this after changing which icons the UI uses. The write is atomic, so a
failed run can never leave a half-written sprite behind.
"""

from __future__ import annotations

import json
import re
import sys
import zipfile
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "web" / "templates"
STATIC = ROOT / "web" / "static"
KNOWLEDGE_BASE = ROOT / "src" / "chatbot" / "data" / "knowledge_base.json"
SPRITE = TEMPLATES / "_icons.html"

# The upstream lucide icon release bundled inside the pinned `lucide` package.
# Recorded here so the generated file can name it; see the package CHANGELOG
# (lucide==1.1.4 -> "upgrade lucide icons version to 1.23.0").
UPSTREAM_LUCIDE_ICONS = "1.23.0"

SVG_NS = "http://www.w3.org/2000/svg"

# `<use href="#i-name">` in a template. The dynamic Jinja form
# (`#i-{{ t.lucide }}`) is deliberately NOT matched here - those names come from
# the knowledge base instead, and the `|default('x')` fallback is picked up by
# _DEFAULT_RE so the fallback icon is never missed.
_USE_RE = re.compile(r'href="#i-([a-z0-9-]+)"')
_DEFAULT_RE = re.compile(r"#i-\{\{[^}]*?\|\s*default\(\s*['\"]([a-z0-9-]+)['\"]")
_JS_ICON_RE = re.compile(r"""\bicon\(\s*['"]([a-z0-9-]+)['"]""")


def _icon_zip() -> zipfile.ZipFile:
    """Open the SVG archive shipped inside the installed lucide package."""
    try:
        import lucide
    except ImportError:  # pragma: no cover - environment problem, not logic
        raise SystemExit(
            "The 'lucide' package is not installed.\n"
            "It is the icon source for this generator. Install it with:\n"
            "    pip install -r requirements.txt"
        )
    archive = Path(lucide.__file__).resolve().parent / "lucide.zip"
    if not archive.is_file():
        raise SystemExit(f"lucide package has no icon archive at {archive}")
    return zipfile.ZipFile(archive)


def lucide_package_version() -> str:
    try:
        return pkg_version("lucide")
    except PackageNotFoundError:  # pragma: no cover
        return "unknown"


def discover() -> dict[str, list[str]]:
    """Return ``{icon-name: [where it is used, ...]}`` discovered from the UI."""
    found: dict[str, set[str]] = {}

    def note(name: str, where: str) -> None:
        found.setdefault(name, set()).add(where)

    for path in sorted(TEMPLATES.glob("*.html")):
        if path.name == SPRITE.name:
            continue  # the sprite defines icons, it does not consume them
        text = path.read_text(encoding="utf-8")
        for name in _USE_RE.findall(text):
            note(name, path.name)
        for name in _DEFAULT_RE.findall(text):
            note(name, f"{path.name} (fallback)")

    for path in sorted(STATIC.glob("*.js")):
        text = path.read_text(encoding="utf-8")
        for name in _JS_ICON_RE.findall(text):
            note(name, path.name)

    if KNOWLEDGE_BASE.is_file():
        data = json.loads(KNOWLEDGE_BASE.read_text(encoding="utf-8-sig"))

        # Walk the whole document rather than assuming a fixed shape: any
        # `"lucide": "name"` field anywhere is an icon the UI can render via
        # chat.html's dynamic `#i-{{ t.lucide }}`. Restructuring the knowledge
        # base must not silently drop icons from the sprite.
        def walk(node: object) -> None:
            if isinstance(node, dict):
                name = str(node.get("lucide", "")).strip()
                if name:
                    note(name, "knowledge_base.json")
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(data)

    return {name: sorted(found[name]) for name in sorted(found)}


def _symbol_xml(name: str, archive: zipfile.ZipFile) -> str:
    """Render one ``<symbol>`` from the packaged upstream SVG for *name*.

    The geometry elements are copied verbatim from the upstream file - this
    function only rewrites the wrapper ``<svg>`` into a ``<symbol>``. No path
    data is authored, reformatted or optimised here.
    """
    try:
        raw = archive.read(f"{name}.svg")
    except KeyError:
        raise SystemExit(
            f"Icon {name!r} is used by the UI but does not exist in lucide "
            f"{UPSTREAM_LUCIDE_ICONS}. Fix the icon name at its call site, or "
            f"pick an icon that lucide actually ships - do not hand-draw one."
        )

    svg = ElementTree.fromstring(raw.decode("utf-8"))
    lines = [f'  <symbol id="i-{name}" viewBox="{svg.attrib.get("viewBox", "0 0 24 24")}">']
    for child in svg:
        tag = child.tag.split("}")[-1]
        attrs = "".join(
            f' {key}="{value}"' for key, value in child.attrib.items()
        )
        lines.append(f"    <{tag}{attrs}/>")
    lines.append("  </symbol>")
    return "\n".join(lines)


def render(icons: dict[str, list[str]]) -> str:
    """Build the whole sprite file contents."""
    archive = _icon_zip()
    with archive:
        symbols = "\n".join(_symbol_xml(name, archive) for name in icons)

    return f"""{{# GENERATED FILE - DO NOT EDIT BY HAND.

   Generated by tools/icontool.py from the `lucide` PyPI package
   (lucide=={lucide_package_version()}, bundling upstream lucide icons
   v{UPSTREAM_LUCIDE_ICONS}). The geometry below is copied verbatim from the
   packaged upstream SVG files - path data is never hand-transcribed.

   Contains exactly the {len(icons)} icons the UI actually references, discovered
   from the templates, web/static/chat.js and the `lucide` field in
   knowledge_base.json. To change the set, change which icons the UI uses and
   regenerate:

       python tools/icontool.py

   Used via <svg class="icon"><use href="#i-name"></use></svg>. Stroke styling
   comes from .icon in style.css so the icons inherit currentColor. #}}
<svg xmlns="{SVG_NS}" style="display:none" aria-hidden="true"
     fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round">
{symbols}
</svg>
"""


def write_atomically(text: str) -> None:
    """Write the sprite via a temp file + replace, so a crash can't truncate it."""
    tmp = SPRITE.with_suffix(".html.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(SPRITE)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "generate"
    icons = discover()

    if not icons:
        raise SystemExit("No icon usages discovered - refusing to write an empty sprite.")

    if cmd == "list":
        print(f"{len(icons)} icons discovered in use:\n")
        for name, where in icons.items():
            print(f"  i-{name:<20} {', '.join(where)}")
        return 0

    text = render(icons)

    if cmd == "check":
        current = SPRITE.read_text(encoding="utf-8") if SPRITE.is_file() else ""
        if current != text:
            print("OUT OF DATE - run `python tools/icontool.py` to regenerate.")
            return 1
        print(f"OK - _icons.html is up to date ({len(icons)} icons).")
        return 0

    if cmd not in ("generate", ""):
        print(__doc__)
        return 0

    write_atomically(text)
    print(
        f"Wrote {SPRITE.relative_to(ROOT)} - {len(icons)} icons from "
        f"lucide=={lucide_package_version()} (upstream icons v{UPSTREAM_LUCIDE_ICONS})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
