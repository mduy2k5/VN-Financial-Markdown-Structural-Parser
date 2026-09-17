from __future__ import annotations

import re
from dataclasses import dataclass

from .guide import UniversalGuide
from .models import SourceLine, StatementContext
from .primitives import extract_periods, extract_unit
from .textnorm import fold


YEAR_RE = re.compile(r"\b20\d{2}\b")
FORM_CODE_RE = re.compile(r"(?i)\b(?:B0?[1-4](?:[A-Z])?(?:[-/][A-Z0-9]+)*|B02/TCTD(?:-HN)?)\b")

FP_HEADINGS = ("bao cao tinh hinh tai chinh", "bang can doi ke toan")
STOP_HEADINGS = {
    "income": ("bao cao ket qua hoat dong", "bao cao ket qua kinh doanh"),
    "cashflow": ("bao cao luu chuyen tien te",),
    "notes": ("thuyet minh bao cao tai chinh", "thuyet minh bctc"),
}
ROOT_LABELS = ("tai san", "no phai tra", "von chu so huu", "tong tai san")


@dataclass
class HeadingCandidate:
    line_no: int
    score: int
    evidence: list[str]
    text: str
    payload_score: int = 0
    projected_end: int | None = None
    span: int | None = None
    final_score: int | None = None


def _nearby(lines: list[SourceLine], center: int, before=8, after=14):
    return [x for x in lines if center - before <= x.line_no <= center + after]


def _contains_any(text: str, aliases) -> bool:
    f = fold(text)
    return any(a in f for a in aliases)




def _statement_heading_text(text: str) -> str:
    """Return the embedded statement title from an explicit metadata line.

    OCR/LLM output sometimes serializes the first statement page as:
      - Tiêu đề: BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT
    while continuation pages use a normal standalone heading.  Treat only
    explicit title keys as headings; ordinary prose mentioning the statement
    name is still rejected.
    """
    raw = (text or "").strip().strip('*_ ')
    m = re.match(
        r"(?i)^(?:[-*]\s*)?(?:tieu de|tiêu đề|ten bao cao|tên báo cáo|report title)\s*:\s*(.+)$",
        raw,
    )
    return m.group(1).strip().strip('*_ ') if m else raw

def _is_heading_like(text: str, aliases) -> bool:
    f = fold(_statement_heading_text(text)).strip()
    # Statement title must begin the line. This rejects prose such as
    # audit-opinion sentences that merely mention the statement name.
    return len(f) <= 180 and any(f.startswith(a) for a in aliases)


def _semantic_root_text(text: str) -> str:
    f = fold((text or "").split("|", 1)[0]).strip()
    f = re.sub(
        r"^(?:(?:[a-z]|[ivxlc]+|\d+(?:\.\d+)*)\s*[-–—.:)]\s*)+",
        "",
        f,
        flags=re.I,
    ).strip()
    return f


def _score_fp_candidate(lines: list[SourceLine], line: SourceLine) -> HeadingCandidate:
    score = 2
    evidence = ["financial_position_heading:+2"]
    window = _nearby(lines, line.line_no)

    has_form_code = any(FORM_CODE_RE.search(x.clean or "") for x in window)
    date_window = [
        x for x in lines
        if line.line_no - 1 <= x.line_no <= line.line_no + 4
    ]
    has_reporting_date = any(
        "tai ngay" in fold(x.clean)
        or "ngay 31 thang 12" in fold(x.clean)
        or re.search(r"\b31[./]12[./]20\d{2}\b", x.clean or "")
        for x in date_window
    )
    same_page_toc = any(
        "muc luc" in fold(x.clean)
        and line.page_no is not None
        and x.page_no == line.page_no
        for x in window
    )
    close_toc = any(
        "muc luc" in fold(x.clean) and abs(x.line_no - line.line_no) <= 8
        for x in window
    )

    # TOC entries can contain form codes too. Treat close TOC as negative only
    # when the candidate does not have a nearby reporting date, which is strong
    # evidence of an actual statement title.
    if same_page_toc or (close_toc and not has_reporting_date):
        score -= 10
        evidence.append("near_toc:-10")

    if has_form_code:
        score += 3
        evidence.append("near_form_code:+3")

    if has_reporting_date:
        score += 2
        evidence.append("near_reporting_date:+2")

    if any(
        any(fold(x.clean).strip() == root or fold(x.clean).startswith(root + " ") for root in ROOT_LABELS)
        for x in window
    ):
        score += 3
        evidence.append("near_financial_root:+3")

    if line.heading_level > 0:
        score += 1
        evidence.append("markdown_heading:+1")

    if any(re.fullmatch(r"\d+\s*-\s*\d+", x.clean.strip()) for x in window if x.clean):
        score -= 2
        evidence.append("near_page_range:-2")

    return HeadingCandidate(line.line_no, score, evidence, line.clean)



def _next_fp_heading_line(lines: list[SourceLine], start_line: int):
    for x in lines:
        if x.line_no <= start_line:
            continue
        if x.clean and _is_heading_like(x.clean, FP_HEADINGS):
            return x.line_no
    return None


def _financial_payload_evidence(lines: list[SourceLine], start_line: int, max_lookahead: int = 180):
    """
    Score whether a heading is followed by an actual financial-position payload.

    This deliberately uses statement-shape evidence instead of aliases so scope
    recovery remains independent from canonical vocabulary.
    """
    hard_end = start_line + max_lookahead

    window = [
        x for x in lines
        if start_line < x.line_no <= hard_end
    ]

    root_hits = set()
    period_value_hits = 0
    code_hits = 0
    numeric_row_hits = 0
    stop_distance = None
    evidence = []

    for x in window:
        f = fold(x.clean or "").strip()

        # A validated next-statement heading very close to this candidate is a
        # strong sign that the candidate came from TOC/cover text.
        if stop_distance is None:
            for kind in ("income", "cashflow", "notes"):
                if _validated_stop(lines, x, kind):
                    stop_distance = x.line_no - start_line
                    break

        semantic = _semantic_root_text(x.clean or "")

        if semantic in {
            "tai san",
            "tai san co",
            "no phai tra",
            "von chu so huu",
            "tong tai san",
            "tong cong tai san",
            "tong nguon von",
            "tong cong nguon von",
        }:
            root_hits.add(semantic)

        if (
            "so cuoi nam" in f
            or "so dau nam" in f
            or re.search(r"\b31[./]12[./]20\d{2}\b", x.clean or "")
        ):
            # Require a numeric/dash payload on the same line when possible.
            if re.search(r"(?<!\d)(?:\(?\d[\d.,]*\)?|[-–—−])(?:\s|$)", x.clean or ""):
                period_value_hits += 1

        if re.search(r"(?i)\b(?:mã số|ma so|chỉ tiêu|chi tieu)\s*[:|]\s*\d{2,3}\b", x.clean or ""):
            code_hits += 1

        if "|" in (x.clean or ""):
            nums = re.findall(r"\(?\d[\d.,]*\)?|[-–—−]", x.clean or "")
            if len(nums) >= 2:
                numeric_row_hits += 1

    score = 0

    if root_hits:
        add = min(8, 2 * len(root_hits))
        score += add
        evidence.append(f"payload_roots:+{add}")

    if period_value_hits:
        add = min(10, period_value_hits)
        score += add
        evidence.append(f"payload_period_values:+{add}")

    if code_hits:
        add = min(6, code_hits)
        score += add
        evidence.append(f"payload_codes:+{add}")

    if numeric_row_hits:
        add = min(6, numeric_row_hits)
        score += add
        evidence.append(f"payload_numeric_rows:+{add}")

    return score, evidence


def _candidate_with_payload(lines: list[SourceLine], c: HeadingCandidate) -> HeadingCandidate:
    payload_score, payload_evidence = _financial_payload_evidence(lines, c.line_no)
    projected_end = find_validated_financial_position_end(lines, c.line_no)
    span = max(0, projected_end - c.line_no)

    final = c.score + payload_score
    evidence = list(c.evidence) + payload_evidence

    max_line = lines[-1].line_no if lines else c.line_no
    if span < 5 and projected_end < max_line:
        final -= 10
        evidence.append("scope_span_lt_5_before_later_content:-10")
    elif span < 5:
        final -= 1
        evidence.append("scope_span_lt_5_at_eof:-1")
    elif span < 15:
        final -= 1
        evidence.append("scope_span_lt_15:-1")
    elif span >= 30:
        final += 2
        evidence.append("scope_span_ge_30:+2")

    return HeadingCandidate(
        line_no=c.line_no,
        score=c.score,
        evidence=evidence,
        text=c.text,
        payload_score=payload_score,
        projected_end=projected_end,
        span=span,
        final_score=final,
    )


def _signature_score_window(lines: list[SourceLine], start_idx: int, window_size: int = 120):
    chunk = lines[start_idx:start_idx + window_size]
    if not chunk:
        return 0

    root_hits = 0
    pv_hits = 0
    code_hits = 0
    table_hits = 0

    for x in chunk:
        f = fold(x.clean or "").strip()
        semantic = _semantic_root_text(x.clean or "")

        if semantic in {
            "tai san",
            "tai san co",
            "no phai tra",
            "von chu so huu",
            "tong tai san",
            "tong cong tai san",
            "tong nguon von",
            "tong cong nguon von",
        }:
            root_hits += 1

        if "so cuoi nam" in f or "so dau nam" in f:
            pv_hits += 1

        if re.search(r"(?i)\b(?:mã số|ma so|chỉ tiêu|chi tieu)\s*[:|]\s*\d{2,3}\b", x.clean or ""):
            code_hits += 1

        if "|" in (x.clean or "") and len(re.findall(r"\(?\d[\d.,]*\)?|[-–—−]", x.clean or "")) >= 2:
            table_hits += 1

    return (
        min(root_hits, 4) * 3
        + min(pv_hits, 8)
        + min(code_hits, 6)
        + min(table_hits, 6)
    )


def find_financial_position_signature_start(lines: list[SourceLine], min_signature_score: int = 12):
    """
    Fallback when statement-title detection is absent or unhealthy.

    Find the earliest dense financial-position region based on root labels,
    code/value attributes and table rows. This handles OCR/LLM files whose
    title is missing, malformed, or only appears in a table of contents.
    """
    best = None

    for i, line in enumerate(lines):
        f = fold(line.clean or "").strip()
        semantic = _semantic_root_text(line.clean or "")

        plausible_root = semantic in {
            "tai san",
            "tai san co",
            "tai san ngan han",
            "tong tai san",
            "tong cong tai san",
        }
        if not plausible_root:
            continue

        score = _signature_score_window(lines, i)
        candidate = (score, -line.line_no, line.line_no)

        if best is None or candidate > best:
            best = candidate

    if best and best[0] >= min_signature_score:
        return best[2], {
            "line_no": best[2],
            "signature_score": best[0],
            "evidence": ["anchor_density_fallback"],
        }

    return None, None


def _is_statement_title_shape(text: str) -> bool:
    """
    Accept standalone statement titles, including an inline reporting date.

    Valid examples:
      Bảng cân đối kế toán hợp nhất tại ngày 31 tháng 12 năm 2025
      Báo cáo tình hình tài chính hợp nhất tại ngày 31 tháng 12 năm 2025
      ... (tiếp theo)

    Audit prose is still rejected because the whole line must start with a known
    title and the suffix must be only consolidation/separate/date/continuation.
    """
    f = fold(_statement_heading_text(text)).strip()
    f = re.sub(r"\s*\((?:tiep theo)\)\s*$", "", f).strip()
    f = re.sub(r"\s+tiep theo\s*$", "", f).strip()

    date_suffix_re = re.compile(
        r"^(?:(?:hop nhat|rieng)\s+)?"
        r"(?:tai\s+ngay\s+\d{1,2}\s+thang\s+\d{1,2}\s+nam\s+20\d{2}"
        r"|tai\s+ngay\s+\d{1,2}[./]\d{1,2}[./]20\d{2})$"
    )

    allowed_suffixes = {"", "hop nhat", "rieng"}
    for base in FP_HEADINGS:
        if f == base:
            return True
        if f.startswith(base + " "):
            suffix = f[len(base):].strip()
            if suffix in allowed_suffixes or date_suffix_re.fullmatch(suffix):
                return True
    return False



def find_validated_financial_position_start(lines: list[SourceLine], min_score=4):
    base_candidates = [
        _score_fp_candidate(lines, line)
        for line in lines
        if line.clean and _is_heading_like(line.clean, FP_HEADINGS)
    ]

    candidates = [_candidate_with_payload(lines, c) for c in base_candidates]

    # A multi-page statement commonly repeats the same heading with
    # "(tiếp theo)" on every page. Those continuation headings belong to one
    # statement cluster and must not compete with the first page.
    #
    # TOC/audit false positives are already penalized by base heading evidence;
    # among genuinely valid statement candidates, prefer the earliest one that
    # has downstream financial payload. This restores page-1 + continuation
    # coverage for multi-page reports.
    valid = [
        c for c in candidates
        if _is_statement_title_shape(c.text)
        and (
            c.score >= min_score
            or (
                "tiep theo" in fold(c.text)
                and c.payload_score >= 5
                and c.score >= 0
            )
        )
        and (c.final_score if c.final_score is not None else c.score) >= min_score
    ]

    # Prefer candidates that project to a real multi-line statement whenever
    # such a candidate exists. If this is only a tiny synthetic/unit document,
    # retain the short candidate rather than falling back to the entire file.
    healthy = [c for c in valid if (c.span or 0) >= 5]
    if healthy:
        valid = healthy

    valid.sort(key=lambda c: c.line_no)
    return (valid[0].line_no if valid else None), candidates


def _validated_stop(lines: list[SourceLine], line: SourceLine, kind: str) -> bool:
    if not _is_heading_like(line.clean, STOP_HEADINGS[kind]):
        return False
    window = _nearby(lines, line.line_no, before=5, after=10)
    if any("muc luc" in fold(x.clean) for x in window):
        return False

    score = 1 if line.heading_level > 0 else 0
    if any(re.search(r"\b20\d{2}\b", x.clean or "") for x in window):
        score += 1
    if any(FORM_CODE_RE.search(x.clean or "") for x in window):
        score += 2
    if kind == "notes" and "thuyet minh bao cao tai chinh" in fold(line.clean):
        score += 3
    if kind in {"income", "cashflow"}:
        if any("|" in x.clean for x in window):
            score += 1
        if any(x.is_bullet for x in window):
            score += 1
    return score >= 2


def find_validated_financial_position_end(lines: list[SourceLine], start_line: int) -> int:
    max_line = lines[-1].line_no if lines else start_line
    for line in lines:
        if line.line_no <= start_line:
            continue
        for kind in ("income", "cashflow", "notes"):
            if _validated_stop(lines, line, kind):
                return line.line_no - 1
    return max_line


def financial_position_scope(lines: list[SourceLine], mode: str = "financial_position"):
    if not lines:
        return 1, 1, {"mode": mode, "candidates": [], "health": "empty"}

    if mode == "whole":
        return lines[0].line_no, lines[-1].line_no, {
            "mode": "whole",
            "selected_start": lines[0].line_no,
            "selected_end": lines[-1].line_no,
            "candidates": [],
            "health": "whole",
        }

    start, candidates = find_validated_financial_position_start(lines)

    serialized = [
        {
            "line_no": c.line_no,
            "score": c.score,
            "payload_score": c.payload_score,
            "final_score": c.final_score,
            "projected_end": c.projected_end,
            "span": c.span,
            "evidence": c.evidence,
            "text": c.text,
        }
        for c in candidates
    ]

    selected_mode = "validated_financial_position"
    recovery = None

    # A valid repeated title can still occur in the middle of a continued
    # statement page. If a strong financial-root cluster begins earlier than
    # the selected title, prefer the earlier dense region.
    signature_start, signature_debug = find_financial_position_signature_start(lines)
    if (
        start is not None
        and signature_start is not None
        and signature_start < start
        and start - signature_start >= 3
    ):
        candidate_end = find_validated_financial_position_end(lines, signature_start)
        selected_end = find_validated_financial_position_end(lines, start)
        if candidate_end - signature_start > selected_end - start:
            start = signature_start
            selected_mode = "anchor_density_prestart_recovery"
            recovery = signature_debug

    if start is None:
        if signature_start is not None:
            start = signature_start
            selected_mode = "anchor_density_recovery"
            recovery = signature_debug
        else:
            return lines[0].line_no, lines[-1].line_no, {
                "mode": "fallback_whole",
                "selected_start": lines[0].line_no,
                "selected_end": lines[-1].line_no,
                "candidates": serialized,
                "health": "fallback_whole",
                "recovery": None,
            }

    end = find_validated_financial_position_end(lines, start)
    span = max(0, end - start)

    # Final sanity guard. A financial statement cannot realistically be a
    # one-line scope. If title-based scope is tiny, try anchor-density recovery
    # before falling back to whole document.
    if span < 5:
        signature_start, signature_debug = find_financial_position_signature_start(lines)
        if signature_start is not None and signature_start != start:
            recovered_end = find_validated_financial_position_end(lines, signature_start)
            if recovered_end - signature_start >= 5:
                start = signature_start
                end = recovered_end
                span = end - start
                selected_mode = "anchor_density_recovery"
                recovery = signature_debug

    health = "healthy" if span >= 5 else "suspicious_tiny_scope"

    return start, end, {
        "mode": selected_mode,
        "selected_start": start,
        "selected_end": end,
        "selected_span": span,
        "candidates": serialized,
        "health": health,
        "recovery": recovery,
    }

def _reporting_year_from_heading_neighborhood(
    lines: list[SourceLine],
    scope_start: int,
):
    """
    Resolve the reporting year from statement evidence near the validated start.

    Priority matters. A form-regulation line may contain 31/12/2014 immediately
    before a 2025 statement title, so scan ALL nearby lines for strong
    'Tại ngày ... năm YYYY' evidence before considering generic numeric dates.
    """
    window = [
        x for x in lines
        if scope_start - 8 <= x.line_no <= scope_start + 24
    ]

    prioritized_patterns = [
        re.compile(r"(?i)\btại ngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+(20\d{2})"),
        re.compile(r"(?i)\bat\s+\d{1,2}\s+\w+\s+(20\d{2})"),
        re.compile(r"(?i)\bngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+(20\d{2})"),
        re.compile(r"(?i)\bcho năm tài chính kết thúc ngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+(20\d{2})"),
        re.compile(r"(?i)\bNăm\s+(20\d{2})\b"),
        re.compile(r"\b31[./]12[./](20\d{2})\b"),
    ]

    for rx in prioritized_patterns:
        for line in window:
            m = rx.search(line.clean or "")
            if m:
                return int(m.group(1))

    return None

def _column_period_labels(
    lines: list[SourceLine],
    guide: UniversalGuide,
    scope_start: int,
    scope_end: int,
):
    """
    Find two distinct reporting period labels from the statement/table header
    area. Headers are stronger than arbitrary dates later in the statement.
    """
    scoped = [x for x in lines if scope_start <= x.line_no <= scope_end]
    result = []

    for line in scoped[:80]:
        # Strong header-ish lines: pipe/table header, period-only line, or lines
        # containing 2+ reporting-period tokens.
        periods = extract_periods(line.clean, line.line_no, guide)
        if not periods:
            continue

        headerish = (
            line.has_pipe
            or line.heading_level > 0
            or len(periods) >= 2
            or len(line.clean) <= 80
        )
        if not headerish:
            continue

        for p in periods:
            if p.raw_period not in result:
                result.append(p.raw_period)
        if len(result) >= 2:
            break

    return result[:2]


def detect_context(
    lines: list[SourceLine],
    guide: UniversalGuide,
    scope_start: int,
    scope_end: int,
):
    scoped = [x for x in lines if scope_start <= x.line_no <= scope_end]

    unit = None
    for line in scoped[:160]:
        if unit is None:
            f = fold(line.clean)
            if "don vi" in f or "don vi tinh" in f or "trieu dong" in f or "trieu vnd" in f:
                unit = extract_unit(line.clean, guide)

    # 1) reporting year from validated statement heading neighborhood.
    report_year = _reporting_year_from_heading_neighborhood(lines, scope_start)

    # 2) two-period column/header context.
    period_candidates = _column_period_labels(
        lines, guide, scope_start, scope_end
    )

    # 3) If heading did not expose a year, infer from header pair.
    if report_year is None:
        years = []
        for raw in period_candidates:
            years.extend(int(x) for x in YEAR_RE.findall(raw))
        if years:
            report_year = years[0]

    current = None
    previous = None

    # Explicit semantic relative labels win.
    for raw in period_candidates:
        f = fold(raw)
        if current is None and any(x in f for x in ("so cuoi nam", "cuoi nam", "nam nay", "du no cuoi nam")):
            current = raw
        if previous is None and any(x in f for x in ("so dau nam", "dau nam", "nam truoc", "du no dau nam")):
            previous = raw

    # Otherwise classify by reporting year.
    if report_year:
        for raw in period_candidates:
            ys = [int(x) for x in YEAR_RE.findall(raw)]
            if not ys:
                continue
            if ys[0] == report_year and current is None:
                current = raw
            elif ys[0] == report_year - 1 and previous is None:
                previous = raw

    if current is None and report_year:
        current = str(report_year)
    if previous is None and report_year:
        previous = str(report_year - 1)

    return StatementContext(
        report_year=report_year,
        current_label=current,
        previous_label=previous,
        unit=unit,
        scope_start=scope_start,
        scope_end=scope_end,
    )
