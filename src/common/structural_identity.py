"""Structural identities for source observations.

Statement codes and note references are source metadata.  They are useful for
audit output, but they are not stable semantic identities: OCR can detach them,
the same code can occur in different schedules, and note references describe a
different document layer.  This module provides the identity used when source
rows are preserved or reconciled.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


def clean_identity_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"[*_`#]+", "", text)
    return re.sub(r"\s+", " ", text).strip(" |:\t\r\n")


def normalize_identity_label(value: Any) -> str:
    text = clean_identity_text(value)
    text = re.sub(r"^\s*(?:\d+|[ivxlcdm]+)\s*[.)-]\s*", "", text, flags=re.I)
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "D").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def structural_identity(
    *,
    statement: str,
    label: Any,
    section: Any = "",
    parent_label: Any = "",
    hierarchy_path: Any = "",
    occurrence_rank: int | None = None,
) -> tuple[str, ...]:
    """Return a code-independent source identity tuple.

    ``occurrence_rank`` is only used when the same normalized label appears
    more than once in the same structural context.  Codes and note references
    are intentionally absent.
    """

    context = hierarchy_path or parent_label or ""
    rank = "" if occurrence_rank is None else str(int(occurrence_rank))
    return (
        clean_identity_text(statement).upper(),
        normalize_identity_label(section),
        normalize_identity_label(context),
        normalize_identity_label(label),
        rank,
    )


def occurrence_rank(
    seen: dict[tuple[str, ...], int],
    *,
    statement: str,
    label: Any,
    section: Any = "",
    parent_label: Any = "",
    hierarchy_path: Any = "",
) -> int:
    """Assign a deterministic one-based rank without using source codes."""

    base = structural_identity(
        statement=statement,
        label=label,
        section=section,
        parent_label=parent_label,
        hierarchy_path=hierarchy_path,
    )
    seen[base] = seen.get(base, 0) + 1
    return seen[base]
