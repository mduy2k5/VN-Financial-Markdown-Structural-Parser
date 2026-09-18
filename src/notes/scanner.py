from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict
from typing import Any, Optional


PAGE_META_RE = re.compile(r"^\s*page\s*:\s*(\d+)\s*$", re.I)
STATEMENT_META_RE = re.compile(r"^\s*statement_type\s*:\s*([A-Za-z_]+)\s*$", re.I)
PAGE_DELIM_RE = re.compile(r"^\s*---\s*$")
PAGE_RANGE_ONLY_RE = re.compile(r"^\s*\d{1,3}\s*(?:[-–—]\s*\d{1,3})?\s*$")
TRAILING_PAGE_RANGE_RE = re.compile(r"(?:^|\s)\d{1,3}\s*(?:[-–—]\s*\d{1,3})?\s*$")
MARKDOWN_TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")
HEADING_PREFIX_RE = re.compile(r"^\s*#{1,6}\s*")
BULLET_PREFIX_RE = re.compile(r"^\s*(?:[-+*•]|\d+[.)])\s+")
BLOCKQUOTE_PREFIX_RE = re.compile(r"^\s*>+\s*")

PRIMARY_TITLE_FOLDS = (
    "bao cao tinh hinh tai chinh",
    "bang can doi ke toan",
    "bao cao ket qua hoat dong kinh doanh",
    "bao cao ket qua kinh doanh",
    "bao cao luu chuyen tien te",
)
NOTES_TITLE_FOLDS = (
    "thuyet minh bao cao tai chinh",
    "ban thuyet minh bao cao tai chinh",
    "thuyet minh ve bao cao tai chinh",
    "thuyet minh bctc",
)
NOTES_CONT_TOKENS = ("tiep theo", "continued")
TOC_TOKENS = ("muc luc", "noi dung trang", "table of contents")


@dataclass
class NotesScope:
    found: bool
    start_line: Optional[int]
    end_line: Optional[int]
    confidence: float
    evidence: list[str]
    sticky: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _TitleCandidate:
    line_no: int
    raw: str
    normalized: str
    score: float
    evidence: list[str]
    rejected: bool = False
    reject_reason: Optional[str] = None


def _fold(value: Any) -> str:
    s = "" if value is None else str(value)
    s = unicodedata.normalize("NFKC", s)
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D").lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def _strip_inline_markdown(value: str) -> str:
    """Chuẩn hóa cách trình bày chỉ để phát hiện scope/tiêu đề.

    Cố ý loại trang trí Markdown mà không đổi source/provenance. Xử lý các dạng
    như:
      **THUYẾT MINH BÁO CÁO TÀI CHÍNH HỢP NHẤT**
      __THUYẾT MINH ...__
      # THUYẾT MINH ...
      > **THUYẾT MINH ...**
      tiêu đề văn bản thuần
    """
    s = unicodedata.normalize("NFKC", value or "").replace("\u00a0", " ")
    s = BLOCKQUOTE_PREFIX_RE.sub("", s)
    s = HEADING_PREFIX_RE.sub("", s)
    s = BULLET_PREFIX_RE.sub("", s)
    s = re.sub(r"\*\*(.*?)\*\*", r"\1", s)
    s = re.sub(r"__(.*?)__", r"\1", s)
    s = re.sub(r"(?<!\*)\*(?!\*)(.*?)\*(?!\*)", r"\1", s)
    s = re.sub(r"(?<!_)_(?!_)(.*?)_(?!_)", r"\1", s)
    s = re.sub(r"`(.*?)`", r"\1", s)
    s = s.replace(r"\*", "*").replace(r"\_", "_")
    return re.sub(r"\s+", " ", s).strip(" |:#-–—\t")


def _normalized_title_line(raw: str) -> str:
    return _fold(_strip_inline_markdown(raw))


def _is_notes_title(raw: str) -> bool:
    f = _normalized_title_line(raw)
    if not f:
        return False
    return any(f.startswith(tok) for tok in NOTES_TITLE_FOLDS)


def _is_notes_continuation(raw: str) -> bool:
    f = _normalized_title_line(raw)
    return _is_notes_title(raw) and any(tok in f for tok in NOTES_CONT_TOKENS)


def _is_primary_title(raw: str) -> bool:
    f = _normalized_title_line(raw)
    return any(f.startswith(tok) for tok in PRIMARY_TITLE_FOLDS)


def _next_nonblank(lines: list[str], idx0: int, limit: int = 5) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    j = idx0 + 1
    while j < len(lines) and len(out) < limit:
        raw = lines[j]
        if raw.strip():
            out.append((j + 1, raw.strip()))
        j += 1
    return out


def _prev_nonblank(lines: list[str], idx0: int, limit: int = 12) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    j = idx0 - 1
    while j >= 0 and len(out) < limit:
        raw = lines[j]
        if raw.strip():
            out.append((j + 1, raw.strip()))
        j -= 1
    return out


def _near_toc(lines: list[str], idx0: int) -> bool:
    # Tìm ngược một heading mục lục gần đó, nhưng dừng xem vùng này là mục lục
    # khi đã gặp tiêu đề báo cáo chính thật. Cách này tránh loại tiêu đề Notes
    # chỉ vì test/báo cáo ngắn có mục lục vài dòng ở phía trên.
    lo = max(0, idx0 - 20)
    toc_idx = None
    for j in range(idx0 - 1, lo - 1, -1):
        f = _fold(_strip_inline_markdown(lines[j]))
        if any(tok in f for tok in TOC_TOKENS):
            toc_idx = j
            break
    if toc_idx is None:
        return False
    for j in range(toc_idx + 1, idx0):
        if _is_primary_title(lines[j]):
            return False
    return True


def _statement_list_reference(lines: list[str], idx0: int, raw: str) -> bool:
    """Phát hiện danh sách ở đầu báo cáo liệt kê các báo cáo được kiểm toán.

    Ví dụ:
      * Bảng cân đối kế toán hợp nhất
      * Báo cáo kết quả hoạt động kinh doanh hợp nhất
      * Báo cáo lưu chuyển tiền tệ hợp nhất
      * Bản thuyết minh báo cáo tài chính hợp nhất
    """
    if not BULLET_PREFIX_RE.match(raw):
        return False
    lo = max(0, idx0 - 8)
    hi = min(len(lines), idx0 + 3)
    primary_siblings = sum(1 for j in range(lo, hi) if j != idx0 and _is_primary_title(lines[j]))
    return primary_siblings >= 2


def _numbered_toc_reference(lines: list[str], idx0: int, raw: str) -> bool:
    # Dạng OCR thường gặp:
    #   7. Bản thuyết minh báo cáo tài chính hợp nhất ...
    #      - Trang: 15-78
    if not re.match(r"^\s*\d{1,2}[.)]\s+", raw):
        return False
    for _, nxt in _next_nonblank(lines, idx0, 3):
        clean = _strip_inline_markdown(nxt)
        nf = _fold(clean)
        if re.match(r"^(?:trang|page)\s*:?\s*\d{1,3}(?:\s*[-–—]\s*\d{1,3})?$", clean, re.I):
            return True
        if re.search(r"\b(?:trang|page)\s*:?\s*\d{1,3}(?:\s*[-–—]\s*\d{1,3})?\s*$", clean, re.I):
            return True
        # Fallback sau fold vì OCR/chuẩn hóa có thể biến dấu câu thành khoảng trắng.
        if re.fullmatch(r"(?:trang|page)\s+\d{1,3}(?:\s+\d{1,3})?", nf):
            return True
        if nf and not PAGE_RANGE_ONLY_RE.fullmatch(nxt):
            break
    return False


def _looks_like_toc_candidate(lines: list[str], idx0: int, raw: str) -> tuple[bool, Optional[str]]:
    """Loại tham chiếu mục lục mà không cần heading mục lục chính thức.

    Trường hợp quan trọng:
      Thuyết minh báo cáo tài chính hợp nhất
      12 - 86
    """
    if _statement_list_reference(lines, idx0, raw):
        return True, "statement_list_reference"
    if _numbered_toc_reference(lines, idx0, raw):
        return True, "numbered_toc_reference"
    if _near_toc(lines, idx0):
        return True, "near_toc_heading"

    stripped = _strip_inline_markdown(raw)
    if MARKDOWN_TABLE_RE.match(raw):
        cells = [x.strip() for x in raw.strip().strip("|").split("|")]
        if any(_is_notes_title(x) for x in cells):
            numeric_cells = [x for x in cells if PAGE_RANGE_ONLY_RE.fullmatch(x)]
            if numeric_cells:
                return True, "toc_table_row_with_page_number"

    # Hậu tố số trang trên cùng dòng: "Thuyết minh ... 12 - 86".
    if TRAILING_PAGE_RANGE_RE.search(stripped) and len(_normalized_title_line(raw).split()) > 4:
        # Không loại năm nằm trong tiêu đề thật; khoảng số trang thường ngắn và ở cuối.
        m = re.search(r"\b(\d{1,3})(?:\s*[-–—]\s*(\d{1,3}))?\s*$", stripped)
        if m and int(m.group(1)) < 200:
            return True, "title_with_trailing_page_number"

    # Số trang/khoảng trang nằm trên một trong các dòng không rỗng ngay sau.
    for _, nxt in _next_nonblank(lines, idx0, 3):
        if PAGE_RANGE_ONLY_RE.fullmatch(nxt):
            return True, "next_line_is_page_number_or_range"
        # Dừng khi nội dung có vẻ là phần thân/heading Notes thật.
        nf = _normalized_title_line(nxt)
        if nf and not nf.startswith(("trang", "page")):
            break

    # Context mục lục thường có một tiêu đề báo cáo khác gần đó kèm số trang.
    prev = _prev_nonblank(lines, idx0, 4)
    nxt = _next_nonblank(lines, idx0, 4)
    neighborhood = prev + nxt
    title_like = sum(1 for _, x in neighborhood if _is_primary_title(x) or _is_notes_title(x))
    page_like = sum(1 for _, x in neighborhood if PAGE_RANGE_ONLY_RE.fullmatch(x))
    if _near_toc(lines, idx0) and title_like >= 1 and page_like >= 1:
        return True, "toc_neighborhood_signature"

    return False, None


def _frontmatter_notes_ranges(lines: list[str]) -> list[tuple[int, int, int | None]]:
    """Trả về các khoảng nội dung có frontmatter trang ghi rõ ``statement_type: notes``."""
    ranges: list[tuple[int, int, int | None]] = []
    i = 0
    n = len(lines)
    while i < n:
        if not PAGE_DELIM_RE.match(lines[i]):
            i += 1
            continue
        j = i + 1
        page = None
        stype = None
        while j < n and not PAGE_DELIM_RE.match(lines[j]):
            pm = PAGE_META_RE.match(lines[j])
            if pm:
                page = int(pm.group(1))
            sm = STATEMENT_META_RE.match(lines[j])
            if sm:
                stype = sm.group(1).casefold()
            j += 1
        if j >= n:
            break
        content_start = j + 1
        k = content_start
        while k < n and not PAGE_DELIM_RE.match(lines[k]):
            k += 1
        if stype == "notes":
            ranges.append((content_start + 1, k, page))
        i = max(k, j + 1)
    return ranges


def _title_candidates(lines: list[str]) -> list[_TitleCandidate]:
    candidates: list[_TitleCandidate] = []
    for idx0, raw in enumerate(lines):
        if not _is_notes_title(raw):
            continue
        score = 10.0
        evidence = ["normalized_notes_title:+10"]
        stripped = raw.strip()

        if HEADING_PREFIX_RE.match(raw):
            score += 2.0
            evidence.append("markdown_heading:+2")
        if re.match(r"^\s*(?:\*\*|__).*?(?:\*\*|__)\s*$", stripped):
            score += 1.5
            evidence.append("markdown_bold_title:+1.5")
        if _is_notes_continuation(raw):
            score -= 1.0
            evidence.append("continuation_title:-1")

        reject, reason = _looks_like_toc_candidate(lines, idx0, raw)
        candidates.append(_TitleCandidate(
            line_no=idx0 + 1,
            raw=raw,
            normalized=_normalized_title_line(raw),
            score=score if not reject else -100.0,
            evidence=evidence + ([f"toc_rejected:{reason}"] if reject else []),
            rejected=reject,
            reject_reason=reason,
        ))
    return candidates


def _scanner_notes_start(scanner_result: Optional[dict]) -> Optional[tuple[int, float]]:
    if not scanner_result:
        return None
    note_ranges = [
        r for r in scanner_result.get("ranges", [])
        if str(r.get("statement_type")) == "NOTES"
    ]
    if not note_ranges:
        return None
    r = min(note_ranges, key=lambda x: int(x.get("start_line") or 10**9))
    return int(r.get("start_line") or 1), float(r.get("confidence") or 0.90)


def detect_notes_scope(text: str, scanner_result: Optional[dict] = None) -> NotesScope:
    """Phát hiện một scope Notes liên tục kèm kiểm tra từ scanner.

    Chính sách v23:
      1. metadata trang rõ ràng có độ ưu tiên cao nhất;
      2. tiêu đề Notes đã chuẩn hóa hỗ trợ dạng heading/in đậm/plain;
      3. tham chiếu mục lục bị loại bằng dấu hiệu số trang cục bộ;
      4. scanner của dự án chỉ là bằng chứng bổ trợ, không có quyền tuyệt đối;
      5. khi Notes bắt đầu, heading giống báo cáo chính bên trong không kết thúc scope.
    """
    lines = text.splitlines()
    evidence: list[str] = []

    # 1) Metadata trang có thẩm quyền khi OCR/frontmatter ghi rõ đây là trang Notes.
    meta_ranges = _frontmatter_notes_ranges(lines)
    if meta_ranges:
        start = min(x[0] for x in meta_ranges)
        evidence.append("page_frontmatter:statement_type=notes")
        scanner = _scanner_notes_start(scanner_result)
        if scanner and abs(scanner[0] - start) <= 8:
            evidence.append("project_statement_scanner:corroborated")
        return NotesScope(True, start, len(lines), 0.995, evidence)

    candidates = _title_candidates(lines)
    valid = [c for c in candidates if not c.rejected]
    scanner = _scanner_notes_start(scanner_result)

    # 2) Ưu tiên tiêu đề thật hợp lệ sớm nhất. Báo cáo thật có thể lặp lại trên trang tiếp nối.
    if valid:
        start_cand = min(valid, key=lambda c: c.line_no)
        confidence = min(0.995, 0.90 + max(0.0, start_cand.score - 8.0) / 50.0)
        evidence.extend(start_cand.evidence)
        evidence.append(f"normalized_title_line:{start_cand.line_no}")

        if scanner:
            scanner_line, scanner_conf = scanner
            if scanner_line == start_cand.line_no or abs(scanner_line - start_cand.line_no) <= 4:
                evidence.append("project_statement_scanner:corroborated")
                confidence = max(confidence, min(0.995, scanner_conf))
            elif scanner_line < start_cand.line_no:
                # Xử lý tài liệu có trang quét đầu tiên là mục lục.
                scanner_raw = lines[scanner_line - 1] if 1 <= scanner_line <= len(lines) else ""
                scanner_is_toc, reason = _looks_like_toc_candidate(lines, scanner_line - 1, scanner_raw)
                if scanner_is_toc or any(c.line_no == scanner_line and c.rejected for c in candidates):
                    evidence.append(f"project_statement_scanner:rejected_toc_start:{scanner_line}")
                else:
                    evidence.append(f"project_statement_scanner:disagrees:{scanner_line}")
            else:
                evidence.append(f"project_statement_scanner:later_candidate:{scanner_line}")

        if any(_is_notes_continuation(lines[c.line_no - 1]) for c in valid[1:]):
            evidence.append("notes_continuation_heading")
        return NotesScope(True, start_cand.line_no, len(lines), confidence, evidence)

    # 3) Chỉ dùng fallback scanner cuối cùng khi dòng của scanner không có dạng mục lục.
    if scanner:
        scanner_line, scanner_conf = scanner
        raw = lines[scanner_line - 1] if 1 <= scanner_line <= len(lines) else ""
        reject, reason = _looks_like_toc_candidate(lines, scanner_line - 1, raw)
        if not reject:
            return NotesScope(
                True, scanner_line, len(lines), min(0.90, scanner_conf),
                ["project_statement_scanner:fallback_validated"],
            )
        evidence.append(f"project_statement_scanner:rejected:{reason}")

    rejected_count = sum(1 for c in candidates if c.rejected)
    if rejected_count:
        evidence.append(f"rejected_title_candidates:{rejected_count}")
    evidence.append("notes_title_not_found")
    return NotesScope(False, None, None, 0.0, evidence)


def primary_heading_decoys_in_scope(text: str, scope: NotesScope) -> list[dict]:
    if not scope.found or scope.start_line is None:
        return []
    lines = text.splitlines()
    out = []
    for idx in range(scope.start_line, (scope.end_line or len(lines)) + 1):
        raw = lines[idx - 1]
        if _is_primary_title(raw):
            out.append({
                "line": idx,
                "text": raw.strip(),
                "normalized": _normalized_title_line(raw),
                "classification": "note_internal_decoy",
            })
    return out


def explain_notes_scope_candidates(text: str) -> list[dict]:
    """Helper chẩn đoán công khai dùng bởi bộ đánh giá coverage v23."""
    lines = text.splitlines()
    return [asdict(c) for c in _title_candidates(lines)]
