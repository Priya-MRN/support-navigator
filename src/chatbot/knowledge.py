"""Knowledge base loading and access helpers.

The knowledge base is a structured JSON document describing each supported
query type (Billing, Orders, Returns, ...) along with keywords for matching
and step-by-step instructions. See ``data/knowledge_base.json``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

# Path to the bundled knowledge base JSON file.
_DATA_PATH = Path(__file__).resolve().parent / "data" / "knowledge_base.json"


@lru_cache(maxsize=1)
def load_knowledge_base(path: str | Path | None = None) -> dict[str, Any]:
    """Load and cache the knowledge base JSON.

    Args:
        path: Optional override path to a knowledge base file. Mainly useful
            for tests. When ``None`` the bundled file is used.

    Returns:
        The parsed knowledge base as a dictionary.
    """
    kb_path = Path(path) if path is not None else _DATA_PATH
    with kb_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def get_query_types(kb: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return the list of all query type definitions."""
    kb = kb or load_knowledge_base()
    return list(kb.get("query_types", []))


def get_query_type(query_id: str, kb: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Return a single query type by its id, or ``None`` if not found."""
    for qt in get_query_types(kb):
        if qt.get("id") == query_id:
            return qt
    return None


def get_sub_topic(
    query_id: str, sub_id: str, kb: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Return a sub-topic dict for a query type, or ``None`` if not found."""
    qt = get_query_type(query_id, kb)
    if not qt:
        return None
    for sub in qt.get("sub_topics", []):
        if sub.get("id") == sub_id:
            return sub
    return None
