"""Quy tắc chất lượng dùng lại cho baseline báo cáo có căn cứ nguồn.

Baseline đã lưu là evidence hữu ích nhưng không tự động là gold standard. Module
này phân loại từng observation mà không cần biết mã chứng khoán hay tên file. Nó
cố ý tách:

* observation đủ điều kiện so sánh kỳ hiện tại/trước đây chính;
* observation cần phân xử vì kỳ, nhãn, scope hoặc evidence nguồn mơ hồ.

Quy tắc dựa trên cấu trúc và không gắn năm. Caller có thể truyền năm báo cáo;
nếu không, năm được suy ra từ evidence baseline.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable


UNKNOWN_PERIODS = {"", "unknown", "unk", "n/a", "na", "none", "null"}
CURRENT_CUES = (
    "current",
    "closing",
    "ending",
    "so cuoi nam",
    "cuoi nam",
    "nam nay",
    "ky nay",
)
PREVIOUS_CUES = (
    "prior",
    "previous",
    "opening",
    "beginning",
    "so dau nam",
    "dau nam",
    "nam truoc",
    "ky truoc",
)
QUARTER_CUES = ("quy i", "quy ii", "quy iii", "quy iv", "quarter")
NON_PRIMARY_WINDOW_CUES = (
    "luy ke",
    "cumulative",
    "year to date",
    "ytd",
)
PLACEHOLDER_LABELS = {
    "chi tieu",
    "ma so",
    "ma",
    "stt",
    "thuyet minh",
    "dien giai",
    "noi dung",
    "nam nay",
    "nam truoc",
    "ky nay",
    "ky truoc",
}


def fold_text(value: Any) -> str:
    text = str(value or "").replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text.lower())
    return " ".join(text.split())


def normalize_label(value: Any) -> str:
    """Chuẩn hóa nhãn báo cáo nhất quán cho so sánh baseline/current.

    Tiền tố bullet số/chữ và hậu tố mã biểu mẫu là cấu trúc trình bày, không
    phải identity của nhãn. Baseline OCR thường giữ ``C NỢ PHẢI TRẢ 300 310 330``
    trong khi parser canonical chỉ giữ ``NỢ PHẢI TRẢ``. Marker kỳ được xử lý ở
    nơi khác, nên hàm này chỉ bỏ nhiễu cấu trúc của nhãn.
    """
    label = fold_text(value)
    if re.search(r"[a-z]", label):
        label = re.sub(r"^(?:\d+(?:\.\d+)*\s+)+", "", label).strip()
        # Section mẫu như ``A. Tài sản`` / ``C. Nợ phải trả`` và marker La Mã
        # không phải identity dòng semantic.
        label = re.sub(r"^(?:[a-z]|[ivxlcdm]{1,4})\s+(?=[a-z])", "", label).strip()
        # Marker mã biểu mẫu/thuyết minh rõ là hậu tố cấu trúc.
        label = re.sub(r"\s+(?:ma so|ma tham chieu|thuyet minh)\b.*$", "", label).strip()
        # Nhiều baseline OCR tách một hoặc nhiều mã số khỏi nhãn. Chỉ bỏ chuỗi
        # số ở cuối sau nhãn text.
        label = re.sub(r"\s+(?:\d+[a-z]?)(?:\s+\d+[a-z]?)*$", "", label).strip()
        # Tham chiếu thuyết minh thường còn dạng ``261 13 b`` / ``8 c`` sau khi
        # bỏ dấu câu. Chúng không thuộc dòng báo cáo.
        label = re.sub(r"\s+\d+(?:\s+\d+)?\s+[a-z]$", "", label).strip()
        label = re.sub(r"\s+(?:chuyen sang trang sau|continued|tiep theo)\b.*$", "", label).strip()
    return label


def parse_number(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if not text or text in {"-", "—", "–", "..."}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    text = re.sub(r"[^0-9,.-]", "", text)
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    elif "," in text:
        head, tail = text.rsplit(",", 1)
        if len(tail) <= 2:
            text = head.replace(",", "") + "." + tail
        else:
            text = text.replace(",", "")
    try:
        result: int | float = float(text) if "." in text else int(text)
    except ValueError:
        return None
    return -result if negative and result > 0 else result


def infer_year_pair(
    document: dict[str, Any],
    *,
    source_text: str | None = None,
) -> tuple[int | None, int | None]:
    """Suy ra năm báo cáo từ evidence kỳ, không từ metadata kiểm toán.

    Cách cũ quét mọi field `raw_text`/`value_raw` rồi chọn năm lớn nhất. Vì vậy,
    ngày phát hành như 2026 có thể lấn át báo cáo có kỳ 2025/2024. Cách hiện tại
    chỉ chấm field kỳ của observation, bỏ dòng hành chính và chỉ dùng tên file
    làm fallback ưu tiên thấp.
    """

    # Artifact canonical của lần chạy hiện tại và baseline mới có quyết định của
    # resolver tài liệu. Dùng lại trước khi quét nhãn/tên file; nếu không evaluator
    # có thể áp dụng policy khác runtime (nhất là báo cáo chốt năm tháng 3 nhưng
    # tên file mang năm trước).
    def explicit_period_pair(obj: dict[str, Any]) -> tuple[int | None, int | None] | None:
        containers = [
            obj.get("period_context"),
            obj.get("year_resolution"),
            obj.get("period"),
            obj.get("periods"),
            obj.get("provenance"),
        ]
        for container in containers:
            if not isinstance(container, dict):
                continue
            nested = container.get("year_resolution")
            if isinstance(nested, dict):
                containers.insert(0, nested)
            current = container.get("current_year", container.get("current"))
            previous = container.get("previous_year", container.get("previous"))
            try:
                current = int(current) if current is not None else None
                previous = int(previous) if previous is not None else None
            except (TypeError, ValueError):
                continue
            if current is not None:
                return current, previous if previous is not None else current - 1
        return None

    if isinstance(document, dict):
        explicit = explicit_period_pair(document)
        if explicit is not None:
            return explicit
        if source_text:
            try:
                from .report_period import infer_report_year_pair

                resolved = infer_report_year_pair(
                    source_text,
                    source_name=str(document.get("source_file") or ""),
                    allow_unknown=True,
                )
                if resolved.get("current_year") is not None:
                    return resolved.get("current_year"), resolved.get("previous_year")
            except (ImportError, ValueError):
                # Giữ fallback baseline cấu trúc cho caller không có tài liệu nguồn đầy đủ.
                pass

    years: Counter[int] = Counter()
    statement_years: set[int] = set()
    metadata_labels = {
        "ngay", "ngay lap", "ngay tao", "ngay cap", "date", "created at",
        "updated at", "page", "so trang", "dia diem", "noi lap", "noi dung",
    }

    def is_metadata_label(value: Any) -> bool:
        label = fold_text(value)
        return (
            label in metadata_labels
            or label.startswith("created at ")
            or label.startswith("updated at ")
            or label.startswith("page ")
            or label.startswith("so trang ")
        )

    def add_period_years(value: Any, weight: int) -> None:
        text = str(value or "")
        if not text:
            return
        # Chỉ đếm năm gắn với marker kỳ/ngày báo cáo. Cách này tránh xem ngày
        # phát hành/kiểm toán trong văn bản tự do là năm báo cáo.
        marker = re.search(
            r"(?i)(?:năm|nam|31\s*[./-]\s*12\s*[./-]|01\s*[./-]\s*01\s*[./-]|"
            r"ngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm|20\d{2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{1,2})",
            text,
        )
        if not marker:
            return
        for match in re.findall(r"\b(20\d{2})\b", text):
            year = int(match)
            years[year] += weight
            statement_years.add(year)

    def visit_statement(statement: dict[str, Any]) -> None:
        for row in statement.get("rows") or []:
            if is_metadata_label(row.get("label")):
                continue
            for observation in row.get("observations") or []:
                period_key = str(observation.get("period_key") or "").strip()
                if re.fullmatch(r"20\d{2}(?:[-/.]\d{1,2}[-/.]\d{1,2})?", period_key):
                    year = int(period_key[:4])
                    years[year] += 10
                    statement_years.add(year)
                add_period_years(observation.get("period_raw"), 5)
                add_period_years(observation.get("raw_text"), 2)

    statements = document.get("statements") if isinstance(document, dict) else None
    if isinstance(statements, dict):
        for statement in statements.values():
            if isinstance(statement, dict):
                visit_statement(statement)
    elif isinstance(document, dict) and isinstance(document.get("rows"), list):
        visit_statement(document)

    # Tên file là anchor năm ở cấp tài liệu. Ưu tiên khi có, nhưng suy ra năm so
    # sánh từ evidence báo cáo để tài liệu chỉ có tên file vẫn theo quy ước hiện tại/trước đây.
    filename_years: list[int] = []
    if isinstance(document, dict):
        source_file = str(document.get("source_file") or "")
        filename_years = [int(match) for match in re.findall(r"(?<!\d)(20\d{2})(?!\d)", source_file)]
    if filename_years:
        current_year = max(filename_years)
        # Tham chiếu pháp lý/mẫu có thể chứa năm rất cũ (ví dụ thông tư năm 2014).
        # Kỳ so sánh nên gần năm tài liệu; nếu không, dùng năm trước thông thường
        # thay vì xem năm trong tham chiếu pháp lý là kỳ so sánh.
        prior_candidates = [
            year for year in statement_years
            if current_year - 2 <= year < current_year
        ]
        previous_year = max(prior_candidates) if prior_candidates else current_year - 1
        return current_year, previous_year

    ordered = sorted(years, key=lambda year: (years[year], year), reverse=True)
    if not ordered:
        return None, None
    return ordered[0], ordered[1] if len(ordered) > 1 else ordered[0] - 1


def period_role(value: Any, current_year: int | None = None, previous_year: int | None = None) -> str:
    """Chuẩn hóa marker kỳ thành current, previous, quarter hoặc unknown."""

    role = fold_text(value)
    if role in UNKNOWN_PERIODS:
        return "unknown"
    # Báo cáo quý có thể lộ cả cửa sổ quý và cửa sổ lũy kế từ đầu năm. Cửa sổ
    # lũy kế không thể thay cho cặp hiện tại/trước đây chính của schema canonical,
    # dù parser trước đó đã làm phẳng period key thành `current`/`prior`.
    if any(cue in role for cue in NON_PRIMARY_WINDOW_CUES):
        return "quarter"
    years = [int(item) for item in re.findall(r"\b(20\d{2})\b", role)]
    # 01/01/current_year là số đầu kỳ và do đó là kỳ so sánh trước đây.
    # Kiểm tra ngày trước test năm chung.
    if re.search(r"\b01\s+01\b", role):
        return "previous"
    if re.search(r"\b31\s+12\b|\b12\s+31\b", role):
        return "current" if current_year and str(current_year) in role else "previous"
    if current_year is not None and current_year in years:
        return "current"
    if previous_year is not None and previous_year in years:
        return "previous"
    if any(cue in role for cue in CURRENT_CUES):
        return "current"
    if any(cue in role for cue in PREVIOUS_CUES):
        return "previous"
    if any(cue in role for cue in QUARTER_CUES):
        return "quarter"
    return "unknown"


def observation_period(
    observation: dict[str, Any],
    current_year: int | None = None,
    previous_year: int | None = None,
) -> str:
    """Giải quyết period_key trước, rồi dùng evidence thô khi key chưa biết."""

    candidates = (
        observation.get("period_key"),
        observation.get("period_role"),
        observation.get("role"),
        observation.get("period_raw"),
        observation.get("raw_text"),
    )
    fallback = "unknown"
    primary_role: str | None = None
    saw_non_primary = False
    for candidate in candidates:
        role = period_role(candidate, current_year, previous_year)
        if role == "quarter":
            saw_non_primary = True
            continue
        if role in {"current", "previous"}:
            primary_role = primary_role or role
            continue
        if role != "unknown":
            fallback = role
    if saw_non_primary:
        return "quarter"
    if primary_role is not None:
        return primary_role
    return fallback


def period_evidence_conflict(
    observation: dict[str, Any],
    current_year: int | None = None,
    previous_year: int | None = None,
) -> bool:
    """Trả về việc key rõ và evidence kỳ thô có mâu thuẫn không."""

    key_role = period_role(observation.get("period_key"), current_year, previous_year)
    if key_role not in {"current", "previous"}:
        return False
    for candidate in (observation.get("period_raw"), observation.get("raw_text")):
        raw_role = period_role(candidate, current_year, previous_year)
        if raw_role in {"current", "previous"} and raw_role != key_role:
            return True
    return False


def is_placeholder_label(value: Any) -> bool:
    label = fold_text(value)
    if not label or label in PLACEHOLDER_LABELS:
        return True
    if re.fullmatch(r"(?:20\d{2})(?:\s+(?:vnd|dong|trieu))?", label):
        return True
    if re.fullmatch(r"(?:nam|ky|quy)\s+20\d{2}(?:\s+.*)?", label):
        return True
    if re.fullmatch(r"[0-9]+(?:\s+[0-9]+)*", label):
        return True
    if label in {
        "vnd", "trieu vnd", "trieu dong", "ma thuyet so minh",
        "nam hien tai", "nam truoc", "nam nay", "ky nay", "ky truoc",
    }:
        return True
    if label.startswith((
        "nam bao cao", "nam nay", "nam truoc", "ky nay", "ky truoc",
        "quy i", "quy ii", "quy iii", "quy iv", "luy ke tu dau nam",
        "so cuoi nam", "so dau nam", "ngay 01 thang", "ngay 31 thang",
        "stt chi tieu", "chi tieu ",
    )):
        return True
    if label.startswith("nam ket thuc ") or label.startswith("ky ket thuc "):
        return True
    return False


def source_period_hint(
    source_lines: list[str] | None,
    source_line: int,
    current_year: int | None,
    previous_year: int | None,
    *,
    lookback: int = 90,
) -> str | None:
    """Suy ra năm section của dòng từ heading nguồn rõ gần nhất."""

    if not source_lines or source_line <= 0 or source_line > len(source_lines):
        return None
    start = max(0, source_line - 1 - lookback)
    for raw in reversed(source_lines[start:source_line - 1]):
        folded = fold_text(raw)
        match = re.search(r"\bnam bao cao\s*:?[ ]*(20\d{2})\b", folded)
        if match:
            return period_role(match.group(1), current_year, previous_year)
        if re.search(r"\bnam nay\b", folded) and len(folded.split()) <= 5:
            return "current"
        if re.search(r"\bnam truoc\b", folded) and len(folded.split()) <= 5:
            return "previous"
    return None


def extract_inline_period_values(
    raw_text: Any,
    current_year: int | None,
    previous_year: int | None,
    leading_value: Any = None,
) -> list[tuple[str, int | float]]:
    """Khôi phục cặp hiện tại/trước đây compact từ một dòng nguồn inline.

    Ví dụ: ``67.231.128 triệu đồng (Năm 2024: 61.748.921)``. Baseline đã lưu
    có thể chỉ chứa một observation cho dòng này và đôi khi gán giá trị đầu vào
    năm trong ngoặc. Khôi phục chỉ dùng cú pháp năm/giá trị rõ, không đoán từ
    số tùy ý trong nhãn.
    """

    text = str(raw_text or "")
    if not text or current_year is None or previous_year is None:
        return []
    value_token = r"[\-–—(]?\d[\d.,]*(?:\))?"
    pairs: list[tuple[str, int | float]] = []

    def parse_inline_number(token: Any) -> int | float | None:
        text = str(token or "").strip()
        # Dòng báo cáo tiếng Việt dùng dấu chấm/phẩy làm phân cách hàng nghìn;
        # một nhóm ba chữ số (``1.934``) vẫn là 1,934, không phải 1.934.
        if re.fullmatch(r"\(?-?\d{1,3}(?:[.,]\d{3})+\)?", text):
            negative = text.startswith("(") or text.startswith("-")
            digits = re.sub(r"[^0-9]", "", text)
            value = int(digits) if digits else None
            return -value if value is not None and negative else value
        return parse_number(text)

    for match in re.finditer(
        rf"(?i)\b(?:năm|nam)\s*(20\d{{2}})\s*:\s*({value_token})",
        text,
    ):
        year = int(match.group(1))
        value = parse_inline_number(match.group(2))
        if value is None or year not in {current_year, previous_year}:
            continue
        pairs.append(("current" if year == current_year else "previous", value))

    date_pattern = re.compile(
        rf"(?i)({value_token})\s*(?:triệu|nghìn)?\s*(?:đồng|vnd|vnđ)?\s*"
        rf"\(\s*(\d{{1,2}})[./-](\d{{1,2}})[./-](20\d{{2}})\s*\)"
    )
    for match in date_pattern.finditer(text):
        value = parse_inline_number(match.group(1))
        if value is None:
            continue
        day = int(match.group(2)); month = int(match.group(3)); year = int(match.group(4))
        if year == current_year and day == 31 and month == 12:
            pairs.append(("current", value))
        elif year == current_year and day == 1 and month == 1:
            pairs.append(("previous", value))
        elif year == previous_year and day == 31 and month == 12:
            pairs.append(("previous", value))

    if pairs and not any(period == "current" for period, _ in pairs):
        before = text[: next(
            (m.start() for m in re.finditer(r"(?i)\b(?:năm|nam)\s*20\d{2}\s*:", text)),
            len(text),
        )]
        # Chỉ dùng giá trị số đầu tiên sau dấu hai chấm đầu của dòng. Cách này
        # tránh xem mã biểu mẫu trong nhãn là observation hiện tại.
        lead_match = re.search(rf":\s*({value_token})", before)
        if lead_match:
            lead = parse_inline_number(leading_value)
            if lead is None:
                lead = parse_inline_number(lead_match.group(1))
            if lead is not None:
                pairs.insert(0, ("current", lead))
    # Cặp ngày/năm là evidence chính thức; không để observation mã sai trong
    # baseline (ví dụ giá trị ``112`` từ ``Mã số: 112``) tồn tại.
    unique: list[tuple[str, int | float]] = []
    for item in pairs:
        if item not in unique:
            unique.append(item)
    return unique


@dataclass(frozen=True)
class ObservationDecision:
    eligible: bool
    period: str
    value: int | float | None
    reasons: tuple[str, ...]


def assess_observation(
    row: dict[str, Any],
    observation: dict[str, Any],
    *,
    current_year: int | None = None,
    previous_year: int | None = None,
    source_line_text: str | None = None,
    manual_review_required: bool = False,
) -> ObservationDecision:
    reasons: list[str] = []
    value = parse_number(observation.get("value"))
    if value is None:
        reasons.append("non_numeric_value")

    label = row.get("label")
    if is_placeholder_label(label):
        reasons.append("placeholder_or_shifted_label")

    period = observation_period(observation, current_year, previous_year)
    if period not in {"current", "previous"}:
        reasons.append("non_primary_period")
    elif period_evidence_conflict(observation, current_year, previous_year):
        reasons.append("period_evidence_conflict")

    try:
        source_line = int(observation.get("source_line"))
    except (TypeError, ValueError):
        source_line = 0
    if source_line <= 0:
        reasons.append("missing_source_line")
    if source_line_text is not None:
        raw_text = str(observation.get("raw_text") or "").strip()
        if not raw_text:
            reasons.append("missing_raw_evidence")
        elif source_line_text.strip() != raw_text:
            reasons.append("source_line_mismatch")

    if manual_review_required:
        reasons.append("baseline_manual_review_required")

    return ObservationDecision(
        eligible=not reasons,
        period=period,
        value=value,
        reasons=tuple(sorted(set(reasons))),
    )


def evidence_key(row: dict[str, Any], decision: ObservationDecision) -> tuple[str, str, int | float]:
    return (normalize_label(row.get("label")), decision.period, decision.value)  # type: ignore[arg-type]  # chỉ thị bỏ qua kiểm tra kiểu cho đối số


def iter_observations(statement: dict[str, Any]) -> Iterable[tuple[dict[str, Any], dict[str, Any]]]:
    for row in statement.get("rows") or []:
        for observation in row.get("observations") or []:
            yield row, observation
