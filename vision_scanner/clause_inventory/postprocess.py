"""Post-extraction normalization passes.

Two fixes applied to the Gemini-emitted document:

1. **Synthetic section-5 header.** Gemini emits `5.table` but no parent
   `5` clause (the takanon doesn't have a distinct §5 heading clause —
   the table IS section 5). We insert a synthetic top-level
   `clause_id: "5"` so `5.table.parent_id="5"` resolves cleanly through
   automated check #4.

2. **`section_title_chain` fill.** Gemini reliably populates the chain
   on header clauses but leaves it empty (`[]`) on most operative
   leaves (~68% of clauses on the M0 run). We compute the chain
   deterministically by walking `parent_id` up to the root, using each
   ancestor's `clause_text` as the chain element. Header clauses
   (those with `is_normative=false` AND `is_quantitative=false`) also
   append their own text at the tail — matching the convention Gemini
   uses for the headers it gets right.

Idempotent: running twice produces the same document.
"""

from __future__ import annotations

from typing import Any, Dict, List

SYNTHETIC_FIVE_FALLBACK_TITLE = "מצב מוצע- טבלת זכויות והוראות בניה"


def _is_header(clause: Dict[str, Any]) -> bool:
    return not clause.get("is_normative") and not clause.get("is_quantitative")


def _ensure_section_5(clauses: List[Dict[str, Any]]) -> None:
    by_id = {c["clause_id"]: c for c in clauses}
    table = by_id.get("5.table")
    if table is None or "5" in by_id:
        if table is not None and table.get("parent_id") != "5":
            table["parent_id"] = "5"
        return

    existing_chain = table.get("section_title_chain") or []
    title = existing_chain[0] if existing_chain else SYNTHETIC_FIVE_FALLBACK_TITLE

    synthetic = {
        "clause_id": "5",
        "parent_id": None,
        "section_title_chain": [title],
        "clause_text": title,
        "page": table.get("page", 16),
        "category": "building_rights",
        "is_quantitative": False,
        "is_normative": False,
    }

    insert_at = next(
        (i for i, c in enumerate(clauses) if c["clause_id"] == "5.table"),
        len(clauses),
    )
    clauses.insert(insert_at, synthetic)
    table["parent_id"] = "5"


def _fill_chains(clauses: List[Dict[str, Any]]) -> None:
    by_id = {c["clause_id"]: c for c in clauses}
    for clause in clauses:
        ancestors: List[str] = []
        seen: set = {clause["clause_id"]}
        cursor_parent = clause.get("parent_id")
        while cursor_parent is not None:
            if cursor_parent in seen:
                break
            seen.add(cursor_parent)
            parent = by_id.get(cursor_parent)
            if parent is None:
                break
            ancestors.append(parent.get("clause_text", ""))
            cursor_parent = parent.get("parent_id")
        ancestors.reverse()
        if _is_header(clause):
            ancestors.append(clause.get("clause_text", ""))
        clause["section_title_chain"] = ancestors


def apply_postprocess(document: Dict[str, Any]) -> Dict[str, Any]:
    clauses: List[Dict[str, Any]] = document.get("clauses", [])
    _ensure_section_5(clauses)
    _fill_chains(clauses)
    document["clauses"] = clauses
    return document
