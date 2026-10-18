"""Documentation checks."""

from __future__ import annotations

from pathlib import Path
import re

STATIC = Path(__file__).parent.parent / "docs" / "_static"


def _without_colours(path: Path) -> str:
    return re.sub(
        r":root \{.*?\}", "", path.read_text(encoding="utf-8"), flags=re.DOTALL
    )


def test_diagram_variants_match() -> None:
    """The light and dark diagrams differ only in their colours."""
    light = _without_colours(STATIC / "async-measure-light.svg")
    dark = _without_colours(STATIC / "async-measure-dark.svg")
    assert light == dark
