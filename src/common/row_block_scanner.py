"""Fast, conservative row-block discovery for Markdown statements.

The scanner is deliberately not a semantic mapper.  It finds likely statement
anchors and partitions a selected statement scope into small source windows so
the existing collectors can read less text when the boundaries are reliable.
Every decision is reversible: callers can keep the diagnostics only (shadow
mode) or fall back to the full-scope collectors when the scan is ambiguous.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable


ROW_BLOCK_SCAN_VERSION = "row_block_v1"
_CODE_RE = re.compile(r"^(?P<code>\d{1,3}(?:\.\d+)*|[IVXLCDM]+)[.)\-:]?\s+(?P<label>.+)$", re.I)
_CODE_MARKER_RE = re.compile(
    r"(?i)^(?:mã\s*số|ma\s*so|mã|ma|ms|số)\s*:\s*(?P<code>\d{1,4}(?:\.\d+)*|[IVXLCDM]+)\s*$"
)
_LABEL_FIELD_RE = re.compile(
    r"(?i)^(?:chỉ\s*tiêu|chi\s*tiêu|diễn\s*giải|dien\s*giai)\s*:\s*(?P<label>.+)$"
)
_PIPE_CODE_RE = re.compile(r"^(?:0*\d{1,4}(?:\.\d+)*|[IVXLCDM]+)$", re.I)
_YEAR_RE = re.compile(r"\b20\d{2}\b")
_PAGE_RE = re.compile(r"(?i)^#{1,6}\s*page\s+\d+")


def _strip_markdown(value: Any) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[*_`~]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip(" |:")


def _fold(value: Any) -> str:
    text = _strip_markdown(value)
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "D").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _indent(raw: str) -> int:
    prefix = raw[: len(raw) - len(raw.lstrip())]
    return len(prefix.expandtabs(4))


def _remove_list_marker(text: str) -> str:
    return re.sub(r"^(?:[*+\-]|\d+[.)])\s+", "", text.strip())


def _is_numeric_cell(value: str) -> bool:
    value = _strip_markdown(value).strip()
    return bool(re.fullmatch(r"\(?[-−]?\d[\d., ]*\)?|[-–—]", value))


def _is_noise(text: str) -> bool:
    folded = _fold(text)
    if not folded:
        return True
    if folded in {
        "content", "metadata", "chi tieu", "ma so", "ma", "stt",
        "thuyet minh", "nam nay", "nam truoc", "ky nay", "ky truoc",
        "don vi", "vnd", "dong", "page", "trang", "phan bo cho",
    }:
        return True
    if folded.startswith((
        "bao cao tai chinh", "bao cao ket qua", "bao cao luu chuyen",
        "cong ty ", "don vi tinh", "ban hanh theo", "cac thuyet minh",
        "thuyet minh bao cao", "search folder", "s3 key", "file name",
        "created at", "updated at", "page ocr",
        "id ", "page ", "trang ", "category ", "filename ", "period ",
        "status ", "symbol ", "year ", "pageocrat", "pageocrstatus",
        "s3key", "searchfolder", "createdat", "updatedat",
    )):
        return True
    if _YEAR_RE.fullmatch(folded) or re.fullmatch(r"(?:nam|ky)\s+20\d{2}", folded):
        return True
    if re.fullmatch(r"(?:nam|ky)\s+(?:nay|truoc)", folded):
        return True
    return False


def _section_for(label: str, current: str | None) -> str | None:
    folded = _fold(label)
    for name, terms in {
        "operating": ("hoat dong kinh doanh", "hoat dong kinh doanh tai chinh"),
        "investing": ("hoat dong dau tu",),
        "financing": ("hoat dong tai chinh",),
        "reconciliation": (
            "tien va cac khoan tuong duong tien",
            "tang giam tien thuan",
            "anh huong cua thay doi ty gia",
        ),
    }.items():
        if any(term in folded for term in terms):
            return name
    return current


def _anchor_from_line(raw: str, line_no: int, profile: str) -> dict[str, Any] | None:
    """Return a likely semantic anchor, never a value-only/metadata line."""

    stripped = raw.strip()
    if not stripped or stripped in {"---", "***", "___"}:
        return None
    if _PAGE_RE.match(stripped) or stripped.startswith("#"):
        return None

    # Pipe tables: the first two cells normally contain code + label.  Keep
    # this separate from the general numbered-line rule because the last two
    # cells are period values and must never become the label.
    if raw.count("|") >= 3:
        cells = [_strip_markdown(cell) for cell in raw.strip().strip("|").split("|")]
        code_index = next((i for i, cell in enumerate(cells[:3]) if _PIPE_CODE_RE.fullmatch(cell)), None)
        if code_index is not None:
            text_cells = [
                cell for i, cell in enumerate(cells[: max(code_index + 2, len(cells) - 2)])
                if i != code_index and re.search(r"[A-Za-zÀ-ỹ]", cell) and not _is_numeric_cell(cell)
            ]
            if text_cells:
                return {
                    "line_no": line_no,
                    "label": max(text_cells, key=len),
                    "code": cells[code_index],
                    "indent": _indent(raw),
                    "kind": "pipe_code",
                    "confidence": 0.97,
                    "raw_text": raw.rstrip(),
                }

    # Markdown emphasis removal can erase the leading ``*`` that was only a
    # bullet marker.  Try the numbered statement form before stripping a
    # numeric list marker; otherwise ``01. Doanh thu`` would lose its code.
    raw_clean = _strip_markdown(raw)
    direct_code_match = _CODE_RE.match(raw_clean)
    clean = raw_clean if direct_code_match else _remove_list_marker(raw_clean)
    code_match = _CODE_RE.match(clean)
    if code_match and code_match.group("code").isalpha() and not re.match(
        r"(?i)^[ivxlcdm]+[.)\-:]\s+", clean
    ):
        # ``id:``, ``createdat:`` and similar metadata can begin with Roman
        # numeral letters.  Only accept Roman anchors when punctuation makes
        # the ordinal explicit (for example ``I. Lãi thuần``).
        code_match = None
    if code_match and re.search(r"[A-Za-zÀ-ỹ]", code_match.group("label")):
        label = code_match.group("label").strip()
        if not _is_noise(label):
            code = code_match.group("code")
            # Roman numerals are useful for B03 totals, but a bare section
            # heading should not be treated as a row anchor.
            confidence = 0.93 if code[0].isdigit() else 0.88
            return {
                "line_no": line_no,
                "label": label,
                "code": code,
                "indent": _indent(raw),
                "kind": "ordinal_code",
                "confidence": confidence,
                "raw_text": raw.rstrip(),
            }

    label_match = _LABEL_FIELD_RE.match(clean)
    if label_match:
        label = label_match.group("label").strip()
        if label and not _is_noise(label):
            return {
                "line_no": line_no,
                "label": label,
                "code": None,
                "indent": _indent(raw),
                "kind": "label_field",
                "confidence": 0.86,
                "raw_text": raw.rstrip(),
            }

    # B03 and some OCR layouts use a bold/bullet label without a numeric code.
    # Accept it only when the line is visibly a list item and has accounting
    # text; this remains a low-confidence anchor and is never used alone to
    # change semantic identity.
    visible = raw.strip()
    has_list = bool(re.match(r"^(?:[*+\-]|\d+[.)])\s+", visible))
    has_bold = "**" in visible or "__" in visible
    if has_list and has_bold and re.search(r"[A-Za-zÀ-ỹ]{4}", clean) and not _is_noise(clean):
        if not re.match(r"(?i)^(?:mã|ma|số|so|năm|nam|kỳ|ky|thuyết|thuyet)\b", clean):
            return {
                "line_no": line_no,
                "label": clean,
                "code": None,
                "indent": _indent(raw),
                "kind": "bold_label",
                "confidence": 0.71,
                "raw_text": raw.rstrip(),
            }
    return None


def _code_marker(raw: str) -> str | None:
    clean = _remove_list_marker(_strip_markdown(raw))
    match = _CODE_MARKER_RE.match(clean)
    return match.group("code") if match else None


def _hard_boundary(raw: str) -> str | None:
    stripped = raw.strip()
    folded = _fold(raw)
    if stripped in {"---", "***", "___"}:
        return "separator"
    if _PAGE_RE.match(stripped) or folded.startswith("page ") or folded.startswith("trang "):
        return "page_boundary"
    if stripped.startswith("#") and not _PAGE_RE.match(stripped):
        return "heading_boundary"
    if folded in {"metadata", "content"}:
        return "document_boundary"
    if folded.startswith(("**metadata", "**content")):
        return "document_boundary"
    return None


def _public_block(block: dict[str, Any], include_raw_lines: bool = False) -> dict[str, Any]:
    result = {
        key: value
        for key, value in block.items()
        if key != "raw_lines"
    }
    if include_raw_lines:
        result["raw_lines"] = list(block.get("raw_lines") or [])
    return result


def _merge_line_ranges(ranges: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """Return sorted, non-overlapping inclusive line ranges."""

    normalized = sorted(
        (int(start), int(end))
        for start, end in ranges
        if int(end) >= int(start)
    )
    merged: list[tuple[int, int]] = []
    for start, end in normalized:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def scan_row_blocks(
    text: str,
    start_line: int,
    end_line: int,
    *,
    profile: str = "generic",
    include_raw_lines: bool = False,
) -> dict[str, Any]:
    """Scan a 1-based source scope into conservative row blocks.

    A block starts at a likely indicator anchor and ends immediately before the
    next anchor at the same or shallower indentation.  The result also exposes
    ``read_start_line``/``read_end_line``: consecutive anchor payload windows
    that can be passed to local collectors.  The scanner does not decide
    parent/child semantics; it only preserves the nearest source parent as
    evidence.
    """

    lines = text.splitlines()
    start = max(1, int(start_line or 1))
    end = min(len(lines), int(end_line or len(lines)))
    if end < start:
        return {
            "version": ROW_BLOCK_SCAN_VERSION,
            "profile": profile,
            "scope_start_line": start,
            "scope_end_line": end,
            "anchors": 0,
            "blocks": [],
            "eligible": False,
            "reason": "invalid_scope",
        }

    anchors: list[dict[str, Any]] = []
    boundary_lines: dict[int, str] = {}
    section: str | None = None
    for line_no in range(start, end + 1):
        raw = lines[line_no - 1]
        boundary = _hard_boundary(raw)
        if boundary:
            boundary_lines[line_no] = boundary
        candidate = _anchor_from_line(raw, line_no, profile)
        if candidate is None:
            continue
        candidate["section"] = _section_for(candidate.get("label") or "", section)
        section = candidate.get("section") or section
        # Do not add a second anchor for the same physical line.
        if anchors and anchors[-1]["line_no"] == line_no:
            if candidate["confidence"] > anchors[-1]["confidence"]:
                anchors[-1] = candidate
            continue
        anchors.append(candidate)

    # A code marker belongs to the current anchor's block.  It is evidence, not
    # an independent row boundary.
    raw_markers: dict[int, str] = {}
    for line_no in range(start, end + 1):
        code = _code_marker(lines[line_no - 1])
        if code:
            raw_markers[line_no] = code

    if not anchors:
        return {
            "version": ROW_BLOCK_SCAN_VERSION,
            "profile": profile,
            "scope_start_line": start,
            "scope_end_line": end,
            "anchors": 0,
            "blocks": [],
            "eligible": False,
            "reason": "no_anchors",
        }

    blocks: list[dict[str, Any]] = []
    for index, anchor in enumerate(anchors):
        start_no = int(anchor["line_no"])
        next_any = int(anchors[index + 1]["line_no"]) if index + 1 < len(anchors) else None
        next_sibling = None
        for later in anchors[index + 1:]:
            if int(later["indent"]) <= int(anchor["indent"]):
                next_sibling = int(later["line_no"])
                break
        natural_end = (next_sibling - 1) if next_sibling is not None else end
        hard_end = None
        hard_reason = None
        for boundary_line, reason in boundary_lines.items():
            if start_no < boundary_line <= natural_end:
                hard_end = boundary_line - 1
                hard_reason = reason
                break
        block_end = max(start_no, hard_end if hard_end is not None else natural_end)

        marker_codes = [
            code for line_no, code in raw_markers.items()
            if start_no <= line_no <= block_end
        ]
        form_code = marker_codes[0] if marker_codes else anchor.get("code")
        parent = None
        for previous in reversed(anchors[:index]):
            if int(previous["indent"]) < int(anchor["indent"]):
                parent = previous
                break

        read_end = (next_any - 1) if next_any is not None else end
        if hard_end is not None:
            read_end = hard_end
        read_end = max(start_no, read_end)
        confidence = float(anchor["confidence"])
        if hard_end is not None and hard_reason != "separator":
            confidence = min(confidence, 0.62)
        if next_sibling is None:
            confidence = max(0.0, confidence - 0.04)
        boundary_reason = hard_reason or ("next_sibling_anchor" if next_sibling is not None else "scope_end")
        blocks.append({
            "block_id": f"{profile}:{start_no}-{block_end}",
            "start_line": start_no,
            "end_line": block_end,
            "read_start_line": start_no,
            "read_end_line": read_end,
            "next_anchor_line": next_any,
            "anchor_label": anchor.get("label"),
            "anchor_code": anchor.get("code"),
            "form_code": form_code,
            "anchor_kind": anchor.get("kind"),
            "indent": anchor.get("indent", 0),
            "section": anchor.get("section"),
            "parent_anchor_label": parent.get("label") if parent else None,
            "parent_anchor_line": parent.get("line_no") if parent else None,
            "confidence": round(confidence, 4),
            "eligible": confidence >= 0.75 and (hard_end is None or hard_reason == "separator"),
            "boundary_reason": boundary_reason,
            "raw_line_count": block_end - start_no + 1,
            "raw_lines": lines[start_no - 1:block_end],
        })

    # Repeated codes are not rejected as blocks; they are marked so callers do
    # not accidentally use the code as a unique semantic key.
    code_counts: dict[tuple[str, str | None], int] = {}
    for block in blocks:
        code = block.get("form_code")
        if code:
            key = (str(code).lstrip("0") or "0", block.get("section"))
            code_counts[key] = code_counts.get(key, 0) + 1
    ambiguous = 0
    for block in blocks:
        code = block.get("form_code")
        key = (str(code).lstrip("0") or "0", block.get("section")) if code else None
        block["code_ambiguous_in_section"] = bool(key and code_counts.get(key, 0) > 1)
        if block["code_ambiguous_in_section"]:
            block["eligible"] = False
            block["confidence"] = min(float(block["confidence"]), 0.69)
            ambiguous += 1

    eligible_blocks = [block for block in blocks if block.get("eligible")]
    eligible_ranges = _merge_line_ranges(
        (
            (int(block["read_start_line"]), int(block["read_end_line"]))
            for block in eligible_blocks
        )
    )
    covered_lines = sum(end - start + 1 for start, end in eligible_ranges)
    structural_start = min(int(block["start_line"]) for block in eligible_blocks) if eligible_blocks else start
    structural_end = max(int(block["end_line"]) for block in eligible_blocks) if eligible_blocks else start
    structural_lines = max(1, structural_end - structural_start + 1)
    return {
        "version": ROW_BLOCK_SCAN_VERSION,
        "profile": profile,
        "scope_start_line": start,
        "scope_end_line": end,
        "anchors": len(anchors),
        "blocks": [_public_block(block, include_raw_lines=include_raw_lines) for block in blocks],
        "eligible": len(eligible_blocks) >= 2,
        "reason": "ok" if len(eligible_blocks) >= 2 else "insufficient_eligible_blocks",
        "eligible_blocks": len(eligible_blocks),
        "ambiguous_code_blocks": ambiguous,
        "covered_lines": covered_lines,
        "scope_lines": end - start + 1,
        "coverage": round(covered_lines / structural_lines, 6),
        "scanned_structural_start_line": structural_start,
        "scanned_structural_end_line": structural_end,
        "scanned_structural_lines": structural_lines,
        # Assist is intentionally stricter than shadow diagnostics.  A row
        # window is allowed to influence a collector only when it covers almost
        # the whole selected scope and no code is ambiguous in its section.
        "assist_eligible": bool(
            len(eligible_blocks) >= 2
            and ambiguous == 0
            and covered_lines / structural_lines >= 0.85
        ),
    }


def iter_eligible_read_ranges(scan: dict[str, Any]) -> Iterable[tuple[int, int]]:
    """Yield non-overlapping source ranges for local collectors."""

    ranges = []
    for block in scan.get("blocks") or []:
        if not block.get("eligible"):
            continue
        start = int(block.get("read_start_line") or block.get("start_line"))
        end = int(block.get("read_end_line") or block.get("end_line"))
        if end >= start:
            ranges.append((start, end))
    yield from _merge_line_ranges(ranges)


def attach_row_block_evidence(rows: list[dict[str, Any]], scan: dict[str, Any]) -> dict[str, int]:
    """Attach non-authoritative block provenance to extracted raw rows."""

    blocks = [
        block for block in scan.get("blocks") or []
        if block.get("eligible")
    ]
    attached = 0
    ambiguous = 0
    for row in rows or []:
        line_no = row.get("source_line", row.get("line")) if isinstance(row, dict) else None
        if line_no is None:
            continue
        try:
            line_no = int(line_no)
        except (TypeError, ValueError):
            continue
        candidates = [
            block for block in blocks
            if int(block["start_line"]) <= line_no <= int(block["end_line"])
        ]
        if not candidates:
            continue
        candidates.sort(key=lambda block: (int(block["end_line"]) - int(block["start_line"]), -int(block["confidence"] * 10000)))
        if len(candidates) > 1 and (
            int(candidates[0]["end_line"]) - int(candidates[0]["start_line"])
            == int(candidates[1]["end_line"]) - int(candidates[1]["start_line"])
        ):
            ambiguous += 1
            continue
        block = candidates[0]
        row["row_block_id"] = block["block_id"]
        row["row_block_start_line"] = block["start_line"]
        row["row_block_end_line"] = block["end_line"]
        row["row_block_confidence"] = block["confidence"]
        row["row_block_parent_label"] = block.get("parent_anchor_label")
        attached += 1
    return {"attached": attached, "ambiguous": ambiguous}


def summarize_row_block_scan(scan: dict[str, Any] | None) -> dict[str, Any] | None:
    """Remove block payloads before a scan is placed in production metrics."""

    if not isinstance(scan, dict):
        return None
    return {key: value for key, value in scan.items() if key != "blocks"}


__all__ = [
    "ROW_BLOCK_SCAN_VERSION",
    "attach_row_block_evidence",
    "iter_eligible_read_ranges",
    "scan_row_blocks",
    "summarize_row_block_scan",
]
