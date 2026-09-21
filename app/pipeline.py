"""Điểm vào batch cho pipeline đọc báo cáo từ source.

Lớp ứng dụng tìm file, suy luận kỳ và ghi output. Các engine trả về kết quả
trong bộ nhớ; module này ghép chúng thành một report production mà không đọc
output của lần chạy trước.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for _p in (str(ROOT), str(SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src.b01_financial_position import (
    FinancialPositionSourceParser,
)
from src.b02_income import IncomeMapper, adapt_row, extract_income_fallback
from src.b03_cashflow import (
    CashFlowMapper,
    adapt_cashflow_row,
    detect_method as detect_cf_method,
    extract_cashflow_fallback,
)
from src.common import (
    augment_from_rows,
    extract_generic_statement_rows,
    extract_securities_supplemental_cashflow_rows,
    augment_canonical_with_recovered_rows,
    extract_code_period_table,
    hydrate_canonical_by_form_code,
    reconcile_source_observations,
    detect_document_unit,
    fold_text,
    resolve_report_years,
    infer_report_year_pair,
)
from src.common.pipeline_metrics import (
    _scope_text,
    detect_sector_from_scope,
    build_metrics,
    build_cashflow_metrics,
)
from src.common.output_contract import (
    BATCH_SCHEMA_NAME,
    BATCH_SCHEMA_VERSION,
    OUTPUT_SCHEMA_NAME,
    OUTPUT_SCHEMA_VERSION,
    build_production_report,
    clean_notes,
    clean_statement,
    manifest_entry,
    report_filename,
)

try:
    from src.notes.pipeline import NotesPipeline
except ImportError:
    from notes.pipeline import NotesPipeline
try:
    from src.notes.row_exporter import export_note_rows, flatten_note_rows
except ImportError:
    from notes.row_exporter import export_note_rows, flatten_note_rows

try:
    from flat_parser.preprocess import filter_noise
    from flat_parser.statement_scanner import scan_statements
    from flat_parser.statement_locator import StatementLocator
    from flat_parser.textnorm import normalize_lines
except Exception:
    filter_noise = normalize_lines = scan_statements = StatementLocator = None



SCHEMA = ROOT / "resources" / "schemas" / "income_statement_schema.json"
ALIASES = ROOT / "resources" / "schemas" / "income_statement_aliases.json"
CF_SCHEMA = ROOT / "resources" / "schemas" / "cash_flow_schema.json"
CF_ALIASES = ROOT / "resources" / "schemas" / "cash_flow_aliases.json"
SCHEMA_OVERLAYS = ROOT / "resources" / "schemas" / "overlays"
SCHEMA_PROFILES = {
    "baseline": {
        "financial_position_schema": ROOT / "resources" / "schemas" / "financial_position_schema.json",
        "financial_position_aliases": ROOT / "resources" / "schemas" / "financial_position_aliases.json",
        "cash_flow_schema": CF_SCHEMA,
        "cash_flow_aliases": CF_ALIASES,
        "preserve_decimal_branch_rows": False,
    },
    "schema_v1_7": {
        "financial_position_schema": SCHEMA_OVERLAYS / "financial_position_schema_v1_7_0.json",
        "financial_position_aliases": SCHEMA_OVERLAYS / "financial_position_aliases_v1_7_0.json",
        "cash_flow_schema": SCHEMA_OVERLAYS / "cash_flow_schema_v1_2_0.json",
        "cash_flow_aliases": SCHEMA_OVERLAYS / "cash_flow_aliases_v1_2_0.json",
        "preserve_decimal_branch_rows": True,
    },
}
REPORT_ARTIFACT_SUFFIXES = (
    ".income.canonical.json",
    ".cashflow.canonical.json",
    ".financial_position.canonical.json",
    ".comparison.json",
    ".notes.ir.json",
)
NOTES_ROW_SUFFIXES = (".notes_rows.csv", ".notes_rows.json")


@lru_cache(maxsize=3)
def statement_locator(schema_path: str, aliases_path: str) -> Optional[StatementLocator]:
    """Tạo hoặc lấy lại locator cho một cặp schema/alias.

    Đầu vào là hai đường dẫn catalog. Xử lý cache instance để B01, B02 và B03
    không nạp lại alias trong cùng process. Đầu ra là ``StatementLocator``;
    nếu dependency không có thì trả ``None`` để caller dùng fallback.
    """

    if StatementLocator is None:
        return None
    return StatementLocator(schema_path=schema_path, aliases_path=aliases_path)


def attach_locator_metrics(metrics: dict, scope: dict) -> dict:
    """Đưa evidence locator vào metrics của statement.

    Đầu vào là metrics hiện có và scope dict có locator result. Hàm đọc trạng
    thái activation, confidence, alias hit và candidate row rồi cập nhật phần
    ``parser``. Đầu ra là chính metrics đã bổ sung; canonical không bị đổi.
    """

    parser = metrics.setdefault("parser", {})
    locator = scope.get("locator") or {}
    activation = locator.get("activation") or {}
    selected = locator.get("selected_scope") or {}
    parser.update({
        "locator_enabled": bool(locator),
        "locator_activated": bool(activation.get("activated")),
        "locator_reason": activation.get("reason"),
        "locator_confidence": selected.get("confidence"),
        "locator_alias_hits": locator.get("alias_hit_count", 0),
        "locator_candidate_rows": len(locator.get("candidate_rows") or []),
    })
    return metrics


def write_json(path: Path, obj: Any):
    """Ghi một object JSON với UTF-8 và indent ổn định.

    Đầu vào là đường dẫn đích và object JSON-serializable. Hàm tạo parent
    directory rồi ghi file; đầu ra không có giá trị trả về, hiệu ứng là một
    file JSON trên đĩa.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def attach_source_provenance(
    canonical: Optional[dict],
    *,
    source_name: str,
    source_sha256: str,
    current_year: int,
    previous_year: int,
    year_resolution: Optional[dict[str, Any]] = None,
) -> Optional[dict]:
    """Gắn provenance source và kỳ vào canonical hiện tại.

    Đầu vào là canonical tùy chọn, tên/hash source, cặp năm và year resolution.
    Xử lý thêm provenance nếu canonical là dict; output là chính dict đã cập
    nhật hoặc ``None`` nếu statement chưa tạo canonical.
    """
    if not isinstance(canonical, dict):
        return canonical
    canonical["source_name"] = source_name
    canonical["source_sha256"] = source_sha256
    canonical["provenance"] = {
        "source_name": source_name,
        "source_sha256": source_sha256,
        "current_year": current_year,
        "previous_year": previous_year,
    }
    if year_resolution:
        canonical["provenance"]["year_resolution"] = year_resolution
    return canonical


def scan_statement_context(text: str) -> Optional[dict]:
    """Chạy structural scanner dùng chung một lần để tìm scope của Notes.

    Đầu vào là toàn bộ Markdown source. Hàm normalize và filter noise trước khi
    gọi scanner; nếu dependency hoặc scanner lỗi, trả ``None`` để Notes tự xử
    lý fallback. Đầu ra là dict evidence scope, không phải Notes IR.

    Bộ phát hiện scope xem scanner là evidence bổ trợ, không phải nguồn quyết
    định duy nhất. Dùng cùng context cho Notes parser và bộ tạo ground truth
    giúp provenance có thể đối chiếu mà không cần giả định riêng cho report.
    """

    if filter_noise is None or normalize_lines is None or scan_statements is None:
        return None
    try:
        return scan_statements(filter_noise(normalize_lines(text)))
    except Exception:
        return None


def remove_report_artifacts(output_dir: Path, base: str) -> None:
    """Xóa đúng artifact của report đang được chạy lại.

    Đầu vào là audit/output directory và base name của report hiện tại. Hàm
    chỉ xóa các suffix đã khai báo cho đúng report; đầu ra không có giá trị trả
    về.

    Cách này ngăn kết quả cũ tồn tại sau lần chạy một phần, đồng thời không
    xóa rộng hoặc xóa đệ quy dữ liệu của người dùng.
    """
    for suffix in REPORT_ARTIFACT_SUFFIXES:
        (output_dir / f"{base}{suffix}").unlink(missing_ok=True)
    rows_dir = output_dir / "notes_rows"
    for suffix in NOTES_ROW_SUFFIXES:
        (rows_dir / f"{base}{suffix}").unlink(missing_ok=True)


def prune_stale_report_artifacts(output_dir: Path, active_bases: set[str]) -> None:
    """Xóa artifact audit của report không còn trong batch hiện tại.

    Đầu vào là thư mục artifact và tập base name đang active. Hàm chỉ duyệt
    suffix đã biết, không xóa report production ngoài phạm vi. Đầu ra không có
    giá trị trả về.
    """
    if not output_dir.exists():
        return
    for suffix in REPORT_ARTIFACT_SUFFIXES:
        for path in output_dir.glob(f"*{suffix}"):
            if path.is_file() and path.name[: -len(suffix)] not in active_bases:
                path.unlink()
    rows_dir = output_dir / "notes_rows"
    if rows_dir.exists():
        for suffix in NOTES_ROW_SUFFIXES:
            for path in rows_dir.glob(f"*{suffix}"):
                if path.is_file() and path.name[: -len(suffix)] not in active_bases:
                    path.unlink()


def clear_legacy_output(output_dir: Path) -> None:
    """Xóa layout output phẳng cũ mà không chạm vào thư mục người dùng.

    Production contract hiện gồm ``manifest.json`` và ``reports/*.json``.
    File parser/evaluation cũ vẫn được ghi dưới ``audit/`` khi được yêu cầu,
    nhưng file cũ không được nằm cạnh manifest production và bị hiểu là kết
    quả hiện tại.

    Đầu vào là output directory. Xử lý xóa các artifact phẳng cũ đã biết và
    metadata batch cũ; đầu ra không có giá trị trả về.
    """
    for suffix in REPORT_ARTIFACT_SUFFIXES:
        for path in output_dir.glob(f"*{suffix}"):
            if path.is_file():
                path.unlink()
    rows_dir = output_dir / "notes_rows"
    if rows_dir.exists():
        for suffix in NOTES_ROW_SUFFIXES:
            for path in rows_dir.glob(f"*{suffix}"):
                if path.is_file():
                    path.unlink()
        try:
            rows_dir.rmdir()
        except OSError:
            pass
    for filename in ("run_metadata.json", "comparison_summary.json", "comparison_summary.csv"):
        (output_dir / filename).unlink(missing_ok=True)


def prune_stale_production_reports(reports_dir: Path, active_report_filenames: set[str]) -> None:
    """Chỉ giữ report JSON có trong tập source hiện tại.

    Đầu vào là ``reports_dir`` và tên file production đang active. Hàm xóa
    report JSON stale trong đúng thư mục này và không đụng source Markdown.
    """
    if not reports_dir.exists():
        return
    for path in reports_dir.glob("*.json"):
        if path.is_file() and path.name not in active_report_filenames:
            path.unlink()


def ensure_output_is_outside_input(input_path: Path, output_dir: Path) -> None:
    """Từ chối output folder có thể trở thành input Markdown ở lần chạy sau.

    Discovery đệ quy chỉ giới hạn trong cây source do caller chỉ định. Nếu
    ghi file sinh ra bên dưới cây đó, lần chạy sau có thể đọc nhầm summary
    Markdown hoặc source được copy. Vì vậy pipeline kiểm tra boundary trước
    khi tạo output.
    """
    if not input_path.is_dir():
        return
    source_root = input_path.resolve()
    candidate = output_dir.resolve()
    try:
        candidate.relative_to(source_root)
    except ValueError:
        return
    raise ValueError(
        f"Output directory must be outside the Markdown input directory: {candidate}"
    )


def stem_base(path: Path) -> str:
    name = path.stem
    return re.sub(r"\((?:\d+|\d{8}-\d{6})\)$", "", name)


def select_md_files(input_path: Path):
    """Trả về một source Markdown cho mỗi base name đã chuẩn hóa.

    Đầu vào:
    - ``input_path``: một file Markdown hoặc thư mục chứa các file Markdown.

    Xử lý:
    - kiểm tra input;
    - quét cấp đầu tiên, rồi mới quét đệ quy nếu cấp đầu không có file;
    - gom các biến thể cùng base name và chọn một source đại diện.

    Đầu ra:
    - danh sách ``Path`` đã sắp xếp, mỗi báo cáo chỉ xuất hiện một lần.

    Hành vi v8:
    - báo lỗi rõ ràng khi input không tồn tại;
    - nhận một file .md đơn lẻ;
    - quét thư mục được yêu cầu trước;
    - nếu không có .md ở cấp đầu, quét các thư mục con;
    - không âm thầm trả về một batch rỗng.
    """
    if not input_path.exists():
        raise FileNotFoundError(f"Input path does not exist: {input_path.resolve()}")

    if input_path.is_file():
        if input_path.suffix.lower() != ".md":
            raise ValueError(f"Input file is not Markdown: {input_path}")
        return [input_path]

    if not input_path.is_dir():
        raise ValueError(f"Input path is neither a file nor a directory: {input_path}")

    files = sorted(p for p in input_path.glob("*.md") if p.is_file())
    discovery_mode = "top_level"
    if not files:
        files = sorted(p for p in input_path.rglob("*.md") if p.is_file())
        discovery_mode = "recursive"

    if not files:
        raise FileNotFoundError(
            f"No Markdown files found under: {input_path.resolve()} "
            f"(checked top-level and recursively)"
        )

    groups = {}
    for p in files:
        base = stem_base(p)
        groups.setdefault(base, []).append(p)

    chosen = []
    for base, variants in groups.items():
        exact = [p for p in variants if p.stem == base]
        chosen.append(exact[0] if exact else sorted(variants, key=lambda x: (len(x.name), x.name))[0])

    chosen = sorted(chosen)
    print(
        f"[DISCOVERY] input={input_path.resolve()} mode={discovery_mode} "
        f"md_found={len(files)} selected={len(chosen)}"
    )
    return chosen


def run_income(md_path: Path, current_year: int | None = None, previous_year: int | None = None, forced_sector="auto", fallback_unit: Optional[str] = None):
    """Chạy extractor và mapper B02 cho một file Markdown.

    Đầu vào:
    - ``md_path``: đường dẫn source Markdown;
    - ``current_year`` và ``previous_year``: năm đã suy luận hoặc được truyền rõ;
    - ``forced_sector`` và ``fallback_unit``: tùy chọn ngữ cảnh từ caller.

    Xử lý:
    - định vị scope B02;
    - trích xuất row theo nhiều layout;
    - map row vào schema theo sector;
    - bổ sung source recovery, reconcile và tính metrics.

    Đầu ra:
    - dict gồm ``canonical``, ``metrics``, ``rows``, ``scope`` và ``sector``;
    - ``canonical`` là ``None`` khi chưa đủ row hoặc sector để map an toàn.

    Locator chỉ thu hẹp scope ứng viên. Extractor vẫn quyết định ranh giới
    row, còn source recovery chỉ thêm evidence và không thay giá trị đã map.
    """
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    period = resolve_report_years(
        text,
        source_name=md_path.name,
        current_year=current_year,
        previous_year=previous_year,
    )
    current_year = period["current_year"]
    previous_year = period["previous_year"]
    locator = statement_locator(str(SCHEMA), str(ALIASES))
    locator_result = (
        locator.locate(text, profile="income_statement")
        if locator is not None
        else None
    )
    ext = extract_income_fallback(
        text,
        current_year,
        previous_year,
        fallback_unit=fallback_unit,
        locator_result=locator_result,
    )
    raw_rows = ext["rows"]
    rows = []
    for i, r in enumerate(raw_rows):
        try:
            rows.append(adapt_row(r, i, current_year=current_year, previous_year=previous_year))
        except Exception:
            continue

    scoped = _scope_text(text, ext)
    if forced_sector in {"bank", "enterprise", "securities", "insurance"}:
        sector, sector_method = forced_sector, "forced"
    else:
        sector, sector_method = detect_sector_from_scope(scoped, rows)

    # Không tạo canonical toàn giá trị null khi structural extraction không có row.
    # Trả về kết quả chỉ dùng cho chẩn đoán. Cách này tránh tạo file
    # `*.income.canonical.json` không có observation nhưng trông như kết quả hợp lệ.
    if not rows:
        metrics = {
            "status": "no_structural_rows",
            "value_nodes": 0, "current_value_nodes": 0, "previous_value_nodes": 0,
            "mapping": {
                "input_rows": 0, "mapped_rows": 0, "unmapped_rows": 0, "mapping_rate": 0.0,
                "canonical_value_nodes": 0, "current_value_nodes": 0, "previous_value_nodes": 0,
                "current_coverage": 0.0, "previous_coverage": 0.0,
            },
            "parser": {
                "statement_profile": "income_statement", "sector": sector, "sector_method": sector_method,
                "scope_start": ext["scope_start_line"], "scope_end": ext["scope_end_line"],
                "scope_score": ext["scope_score"], "collector_policy": "income_multi_layout_v8",
                "patterns": [],
            },
            "quality": {
                "canonical_status": "no_structural_rows", "formula_evaluated": 0,
                "formula_passed": 0, "formula_failed": 0, "formula_pass_rate": None,
                "sign_normalizations": 0,
            },
            "unmapped_examples": [],
        }
        attach_locator_metrics(metrics, ext)
        return {"canonical": None, "metrics": metrics, "rows": rows, "scope": ext, "sector": sector}

    if sector not in {"bank", "enterprise", "securities", "insurance"}:
        metrics = {
            "status": "unknown_sector",
            "value_nodes": 0, "current_value_nodes": 0, "previous_value_nodes": 0,
            "mapping": {"input_rows": len(rows), "mapped_rows": 0, "unmapped_rows": len(rows), "mapping_rate": 0.0},
            "parser": {
                "statement_profile": "income_statement", "sector": "unknown", "sector_method": sector_method,
                "scope_start": ext["scope_start_line"], "scope_end": ext["scope_end_line"], "scope_score": ext["scope_score"],
                "collector_policy": "income_multi_layout_v8",
            },
            "unmapped_examples": [{"label": r.label, "current": r.current, "previous": r.previous, "code": r.code} for r in rows[:40]],
        }
        attach_locator_metrics(metrics, ext)
        return {"canonical": None, "metrics": metrics, "rows": rows, "scope": ext, "sector": "unknown"}

    mapper = IncomeMapper(schema_path=SCHEMA, aliases_path=ALIASES, sector=sector, regex_fallback=True,
                          regex_min_score=0.93, regex_gap=0.08)
    mapped = mapper.map_rows(rows)
    # `SP_INCOME_CODE_LED_MIXED` là pattern phục hồi. Với layout đã được
    # pattern cấu trúc mạnh hơn bắt được, nó có thể vượt qua ranh giới bullet
    # kế bên và tạo duplicate mâu thuẫn.
    # Chỉ giữ pattern này khi nó là evidence duy nhất; nếu không, observation
    # đầy đủ từ parser chính là kết quả có thẩm quyền.
    complete_primary_nodes = {
        row.node_id
        for row in mapped
        if row.mapping_status == "mapped"
        and row.node_id
        and row.pattern != "SP_INCOME_CODE_LED_MIXED"
        and row.current is not None
        and row.previous is not None
    }
    mapped = [
        row for row in mapped
        if not (
            row.pattern == "SP_INCOME_CODE_LED_MIXED"
            and row.mapping_status == "mapped"
            and row.node_id in complete_primary_nodes
        )
    ]
    stmt_unit = ext.get("unit") or fallback_unit
    if stmt_unit == "unknown":
        stmt_unit = None
    canonical = mapper.canonical(mapped, source_name=md_path.name, current_year=current_year, previous_year=previous_year, statement_unit=stmt_unit)
    canonical = augment_from_rows(canonical, mapped, "INCOME")
    # v13: source-scope recovery chỉ bổ sung. Nó giữ các row semantic extractor
    # chưa tạo ra, nhưng không đổi quyết định map của node đã có giá trị.
    if ext.get("scope_start_line") and ext.get("scope_end_line"):
        recovered_rows = extract_generic_statement_rows(
            text, ext["scope_start_line"], ext["scope_end_line"], current_year, previous_year, "INCOME")
        canonical = augment_canonical_with_recovered_rows(canonical, recovered_rows, "INCOME")
        canonical = reconcile_source_observations(canonical, "INCOME")
    metrics = build_metrics(canonical, mapped, ext, sector, sector_method)
    attach_locator_metrics(metrics, ext)
    sr = (canonical.get("diagnostics") or {}).get("source_statement_recovery") or {}
    (metrics.get("parser") or {}).update({
        "source_recovery": "v16", "source_recovered_rows": sr.get("rows_recovered", 0),
        "source_recovery_added_nodes": sr.get("added_nodes", 0),
        "source_recovery_filled_nodes": sr.get("filled_existing_nodes", 0),
        "source_recovery_conflicts": sr.get("conflicts", 0),
        "source_period_scope_ambiguities": sr.get("period_scope_ambiguities", 0),
    })
    return {"canonical": canonical, "metrics": metrics, "rows": mapped, "scope": ext, "sector": sector}




def run_cashflow(
    md_path: Path,
    current_year: int | None = None,
    previous_year: int | None = None,
    fallback_unit: Optional[str] = None,
    *,
    schema_path: Path | str | None = None,
    aliases_path: Path | str | None = None,
    preserve_decimal_branch_rows: bool = True,
):
    """Chạy extractor và mapper B03 cho một file Markdown.

    Đầu vào:
    - ``md_path``: đường dẫn source Markdown;
    - ``current_year`` và ``previous_year``: cặp năm của báo cáo;
    - ``fallback_unit``: đơn vị tài liệu nếu B03 không tự tìm thấy.

    Xử lý:
    - định vị scope B03;
    - xác định sector và phương pháp direct/indirect;
    - trích xuất, map và hydrate các row có thể bị tách;
    - giữ supplemental section và conflict dưới dạng source observation.

    Đầu ra:
    - dict gồm ``canonical``, ``metrics``, ``rows``, ``scope``, ``sector`` và ``method``;
    - ``canonical`` là ``None`` khi profile hoặc phương pháp chưa đủ an toàn.

    B03 phải xác định section và phương pháp direct/indirect trước khi map.
    Schedule bổ sung được giữ làm source evidence khi schema không có semantic
    target an toàn.
    """
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    schema_path = schema_path or CF_SCHEMA
    aliases_path = aliases_path or CF_ALIASES
    period = resolve_report_years(
        text,
        source_name=md_path.name,
        current_year=current_year,
        previous_year=previous_year,
    )
    current_year = period["current_year"]
    previous_year = period["previous_year"]
    locator = statement_locator(str(schema_path), str(aliases_path))
    locator_result = (
        locator.locate(text, profile="cash_flow")
        if locator is not None
        else None
    )
    ext = extract_cashflow_fallback(
        text,
        current_year,
        previous_year,
        fallback_unit=fallback_unit,
        locator_result=locator_result,
        preserve_decimal_branch_rows=preserve_decimal_branch_rows,
    )
    rows = []
    for raw in ext.get("rows", []):
        try:
            rows.append(adapt_cashflow_row(raw))
        except Exception:
            continue
    sector = ext.get("sector") or "unknown"
    method = ext.get("method") or "unknown"
    sector_method = ext.get("sector_method") or "unknown"
    method_method = ext.get("method_method") or "unknown"
    if method == "unknown" and rows:
        labels_text = "\n".join(r.label for r in rows if getattr(r, "label", None))
        recovered_method, recovered_method_method = detect_cf_method(labels_text)
        if recovered_method in {"direct", "indirect"}:
            method, method_method = recovered_method, "rows_" + recovered_method_method
            for r in rows:
                r.method = method
    if not rows:
        metrics = build_cashflow_metrics(None, rows, ext, sector, sector_method, method, method_method)
        attach_locator_metrics(metrics, ext)
        return {"canonical": None, "metrics": metrics, "rows": rows, "scope": ext, "sector": sector, "method": method}
    # v1 chỉ hỗ trợ các profile statutory đã được nghiên cứu cho TT200 và B04/TCTD.
    # Securities/insurance vẫn được phát hiện, không ép vào schema sai.
    if sector not in {"enterprise", "bank", "securities"} or method not in {"direct", "indirect"}:
        metrics = build_cashflow_metrics(None, rows, ext, sector, sector_method, method, method_method)
        attach_locator_metrics(metrics, ext)
        return {"canonical": None, "metrics": metrics, "rows": rows, "scope": ext, "sector": sector, "method": method}
    mapper = CashFlowMapper(schema_path, aliases_path, sector=sector, method=method)
    mapped = mapper.map_rows(rows)
    stmt_unit = ext.get("unit") or fallback_unit
    if stmt_unit == "unknown":
        stmt_unit = None
    canonical = mapper.canonical(mapped, md_path.name, current_year, previous_year, statement_unit=stmt_unit)
    canonical = augment_from_rows(canonical, mapped, "CASHFLOW")
    # v13: raw source recovery xử lý layout trộn năm/ngày trên cùng dòng, ví dụ
    # giá trị hiện tại đi trước `(Năm 2024: ...)` hoặc `(31.12.2025); (31.12.2024)`,
    # vốn có thể chỉ hydrate được một kỳ ở v12.
    if ext.get("scope_start_line") and ext.get("scope_end_line"):
        recovered_rows = extract_generic_statement_rows(
            text, ext["scope_start_line"], ext["scope_end_line"], current_year, previous_year, "CASHFLOW")
        canonical = augment_canonical_with_recovered_rows(canonical, recovered_rows, "CASHFLOW")
        # v16: bảng statutory chỉ có mã có thể hydrate an toàn node profile duy nhất
        # đã tồn tại. Cách này ghép lại kỳ mà không tự tạo label hoặc ghi đè giá trị.
        code_evidence = extract_code_period_table(
            text, ext["scope_start_line"], ext["scope_end_line"], current_year, previous_year)
        canonical = hydrate_canonical_by_form_code(canonical, code_evidence, sector, method)

        # Report securities có thể thêm schedule dòng tiền khách hàng/đại lý
        # sau các section statutory của B03. Giữ schedule này thành source
# observation có ranh giới: universal schema không có node semantic cho
        # số dư khách hàng, nên map vào node enterprise/bank sẽ kém an toàn hơn
        # việc giữ nguyên evidence.
        supplemental_scope = {"rows": []}
        if sector == "securities":
            supplemental_scope = extract_securities_supplemental_cashflow_rows(
                text, current_year, previous_year
            )
            supplemental_rows = supplemental_scope.get("rows") or []
            if supplemental_rows:
                canonical = augment_canonical_with_recovered_rows(
                    canonical, supplemental_rows, "CASHFLOW"
                )
        canonical = reconcile_source_observations(canonical, "CASHFLOW")
    else:
        supplemental_scope = {"rows": []}
    metrics = build_cashflow_metrics(canonical, mapped, ext, sector, sector_method, method, method_method)
    attach_locator_metrics(metrics, ext)
    sr = (canonical.get("diagnostics") or {}).get("source_statement_recovery") or {}
    (metrics.get("parser") or {}).update({
        "source_recovery": "v16", "source_recovered_rows": sr.get("rows_recovered", 0),
        "source_recovery_added_nodes": sr.get("added_nodes", 0),
        "source_recovery_filled_nodes": sr.get("filled_existing_nodes", 0),
        "source_recovery_conflicts": sr.get("conflicts", 0),
        "supplemental_source_recovered_rows": len(supplemental_scope.get("rows") or []),
        "supplemental_scope_start": supplemental_scope.get("scope_start_line"),
        "supplemental_scope_end": supplemental_scope.get("scope_end_line"),
    })
    return {"canonical": canonical, "metrics": metrics, "rows": mapped, "scope": ext, "sector": sector, "method": method}


def process_one(
    md_path: Path,
    audit_dir: Optional[Path],
    current_year: int,
    previous_year: int,
    sector: str,
    *,
    fp_parser: Optional[FinancialPositionSourceParser] = None,
    enable_notes: bool = True,
    year_resolution: Optional[dict[str, Any]] = None,
    financial_position_schema_path: Optional[Path] = None,
    financial_position_aliases_path: Optional[Path] = None,
    cashflow_schema_path: Optional[Path] = None,
    cashflow_aliases_path: Optional[Path] = None,
    preserve_decimal_branch_rows: bool = True,
):
    """Parse một report và trả về kết quả statement cùng production JSON.

    Đầu vào:
    - ``md_path``: source Markdown cần xử lý;
    - ``audit_dir``: thư mục artifact tùy chọn;
    - năm, sector và các parser tùy chọn từ ``main``.

    Xử lý:
    - đọc source một lần và tạo provenance;
    - chạy B02, B03, B01 theo thứ tự production;
    - chạy Notes sau khi có primary statements;
    - chuyển từng statement sang output contract rồi ghép report envelope.

    Đầu ra:
    - dict production của một báo cáo, kèm statement metrics và Notes;
    - nếu bật audit, các artifact review được ghi riêng nhưng không làm input
      cho lần parse tiếp theo.

    Thứ tự gọi là có chủ ý: B02, B03, B01 rồi Notes bổ sung. Notes nhận kết
    quả primary để link nhưng không trở thành nguồn dữ liệu chính.
    """
    base = stem_base(md_path)
    source_text = md_path.read_text(encoding="utf-8", errors="ignore")
    source_sha256 = hashlib.sha256(md_path.read_bytes()).hexdigest()
    doc_unit_ctx = detect_document_unit(source_text)
    doc_unit = doc_unit_ctx.unit if doc_unit_ctx.unit != "unknown" else None

    if audit_dir is not None:
        audit_dir.mkdir(parents=True, exist_ok=True)
        remove_report_artifacts(audit_dir, base)

    inc = run_income(md_path, current_year, previous_year, sector, fallback_unit=doc_unit)
    cf = run_cashflow(
        md_path,
        current_year,
        previous_year,
        fallback_unit=doc_unit,
        schema_path=cashflow_schema_path,
        aliases_path=cashflow_aliases_path,
        preserve_decimal_branch_rows=preserve_decimal_branch_rows,
    )
    attach_source_provenance(
        inc.get("canonical"),
        source_name=md_path.name,
        source_sha256=source_sha256,
        current_year=current_year,
        previous_year=previous_year,
        year_resolution=year_resolution,
    )
    attach_source_provenance(
        cf.get("canonical"),
        source_name=md_path.name,
        source_sha256=source_sha256,
        current_year=current_year,
        previous_year=previous_year,
        year_resolution=year_resolution,
    )

    if fp_parser is None:
        fp_parser = FinancialPositionSourceParser(
            schema_path=financial_position_schema_path,
            aliases_path=financial_position_aliases_path,
        )
    fp = fp_parser.parse_text(
        source_text,
        source_name=md_path.name,
        source_sha256=source_sha256,
        current_year=current_year,
        previous_year=previous_year,
        fallback_unit=doc_unit,
    )

# Đồng bộ lại đơn vị giữa các báo cáo.
    resolved_unit = (
        doc_unit
        or (inc.get("canonical") or {}).get("unit")
        or (cf.get("canonical") or {}).get("unit")
        or (fp.get("canonical") or {}).get("unit")
    )
    if resolved_unit and resolved_unit != "unknown":
        for obj in (inc.get("canonical"), cf.get("canonical"), fp.get("canonical")):
            if obj:
                if not obj.get("unit") or obj.get("unit") == "unknown":
                    obj["unit"] = resolved_unit
                for n in obj.get("nodes", []):
                    v = n.get("value")
                    if isinstance(v, dict) and (not v.get("unit") or v.get("unit") == "unknown"):
                        cname = fold_text(n.get("canonical_name", ""))
                        if "lai co ban" in cname or "lai suy giam" in cname:
                            v["unit"] = "vnd_per_share"
                        else:
                            v["unit"] = resolved_unit

    income_path = audit_dir / f"{base}.income.canonical.json" if audit_dir else None
    if audit_dir is not None:
        if inc["canonical"] is not None:
            write_json(income_path, inc["canonical"])
        elif income_path.exists():
            income_path.unlink()

    cashflow_path = audit_dir / f"{base}.cashflow.canonical.json" if audit_dir else None
    if audit_dir is not None:
        if cf["canonical"] is not None:
            write_json(cashflow_path, cf["canonical"])
        elif cashflow_path.exists():
            cashflow_path.unlink()

    fp_path = audit_dir / f"{base}.financial_position.canonical.json" if audit_dir else None
    if audit_dir is not None:
        if fp.get("canonical") is not None:
            write_json(fp_path, fp["canonical"])
            fp["canonical_file"] = fp_path.name
        elif fp_path.exists():
            fp_path.unlink()

    # Nền tảng Notes v22.5: chỉ bổ sung, không phá dữ liệu.
# Báo cáo chính vẫn có thẩm quyền; Notes được xuất thành Generic Note IR riêng.
    notes_ir = None
    notes_rows: list[dict[str, Any]] = []
    notes_path = audit_dir / f"{base}.notes.ir.json" if audit_dir else None
    if enable_notes:
        notes_sector = inc.get("sector") or cf.get("sector") or "enterprise"
        primary_for_notes = {
            "financial_position": {"canonical": fp.get("canonical") or {}},
            "income_statement": {"canonical": inc.get("canonical") or {}},
            "cash_flow_statement": {"canonical": cf.get("canonical") or {}},
        }
        notes_ir = NotesPipeline(
            current_year=current_year,
            previous_year=previous_year,
        ).parse_text(
            source_text,
            source_name=md_path.name,
            sector=notes_sector,
            scanner_result=scan_statement_context(source_text),
            primary=primary_for_notes,
        )
        notes_ir["source_sha256"] = source_sha256
        notes_ir["provenance"] = {
            "source_name": md_path.name,
            "source_sha256": source_sha256,
            "current_year": current_year,
            "previous_year": previous_year,
            "year_resolution": year_resolution or {"method": "explicit_function_arguments"},
        }
        if (notes_ir.get("diagnostics") or {}).get("notes_found"):
            notes_rows = flatten_note_rows(notes_ir)
            if audit_dir is not None:
                write_json(notes_path, notes_ir)
                notes_rows_dir = audit_dir / "notes_rows"
                notes_rows_export = export_note_rows(
                    notes_ir,
                    notes_rows_dir,
                    stem=base,
                    write_json=True,
                )
            else:
                notes_rows_export = {
                    "row_count": len(notes_rows),
                    "csv_file": None,
                    "json_file": None,
                }
        else:
            notes_rows_export = {"row_count": 0, "csv_file": None, "json_file": None}
            if notes_path is not None and notes_path.exists():
                notes_path.unlink()
    else:
        notes_rows_export = {"row_count": 0, "csv_file": None, "json_file": None}
    if not enable_notes and notes_path is not None and notes_path.exists():
        notes_path.unlink()

    production = build_production_report(
        source_name=md_path.name,
        source_sha256=source_sha256,
        current_year=current_year,
        previous_year=previous_year,
        year_resolution=year_resolution,
        financial_position=clean_statement(
            fp.get("canonical"), fp.get("metrics"), statement_type="financial_position"
        ),
        income_statement=clean_statement(
            inc.get("canonical"), inc.get("metrics"), statement_type="income_statement"
        ),
        cash_flow=clean_statement(
            cf.get("canonical"), cf.get("metrics"), statement_type="cash_flow"
        ),
        notes=clean_notes(notes_ir, notes_rows),
    )

# File canonical/so sánh chi tiết chỉ dành cho audit.
    # Chúng hữu ích cho evaluation và troubleshooting nhưng không thuộc
    # output contract ổn định dành cho consumer.
    merged_path = None
    if audit_dir is not None:
        merged = {
            "source_name": md_path.name,
            "source_sha256": source_sha256,
            "current_year": current_year,
            "previous_year": previous_year,
            "year_resolution": year_resolution or {"method": "explicit_function_arguments"},
            "financial_position": {
                "v05": fp["metrics"],
                "canonical_file": fp["canonical_file"],
            },
            "income_statement": {
                "v05": inc["metrics"],
                "canonical_file": income_path.name if inc["canonical"] is not None else None,
            },
            "cash_flow_statement": {
                "v01": cf["metrics"],
                "canonical_file": cashflow_path.name if cf["canonical"] is not None else None,
            },
        }
        if notes_ir is not None:
            nd = notes_ir.get("diagnostics") or {}
            merged["notes"] = {
                "schema_id": notes_ir.get("schema_id"),
                "schema_version": notes_ir.get("schema_version"),
                "status": "parsed" if nd.get("notes_found") else "not_detected",
                "ir_file": notes_path.name if nd.get("notes_found") else None,
                "scope_start": notes_ir.get("scope_start_line"),
                "scope_end": notes_ir.get("scope_end_line"),
                "sections": nd.get("section_count", 0),
                "tables": nd.get("table_count", 0),
                "rows": nd.get("row_count", 0),
                "exported_rows": notes_rows_export.get("row_count", 0),
                "rows_csv": (
                    f"notes_rows/{notes_rows_export.get('csv_file')}"
                    if notes_rows_export.get("csv_file") else None
                ),
                "rows_json": (
                    f"notes_rows/{notes_rows_export.get('json_file')}"
                    if notes_rows_export.get("json_file") else None
                ),
                "links": nd.get("link_count", 0),
                "high_confidence_links": nd.get("high_confidence_links", 0),
                "policy": "PRIMARY_GT_NOTES_non_destructive_v1",
            }
        merged_path = audit_dir / f"{base}.comparison.json"
        write_json(merged_path, merged)

    im = inc["metrics"]; imp = im.get("mapping", {})
    cm = cf["metrics"]; cmp = cm.get("mapping", {})
    return {
        "source_name": md_path.name,
        "source_sha256": source_sha256,
        "current_year": current_year,
        "previous_year": previous_year,
        "year_resolution": year_resolution or {"method": "explicit_function_arguments"},
        "sector": inc["sector"], "status": im.get("status"),
        "scope_start": (im.get("parser") or {}).get("scope_start"), "scope_end": (im.get("parser") or {}).get("scope_end"),
        "scope_score": (im.get("parser") or {}).get("scope_score"), "sector_method": (im.get("parser") or {}).get("sector_method"),
        "patterns": ";".join((im.get("parser") or {}).get("patterns", [])),
        "input_rows": imp.get("input_rows", 0), "mapped_rows": imp.get("mapped_rows", 0), "unmapped_rows": imp.get("unmapped_rows", 0),
        "mapping_rate": imp.get("mapping_rate", 0.0), "income_value_nodes": im.get("value_nodes", 0),
        "income_current_nodes": im.get("current_value_nodes", 0), "income_previous_nodes": im.get("previous_value_nodes", 0),
        "current_coverage": imp.get("current_coverage", 0.0), "previous_coverage": imp.get("previous_coverage", 0.0),
        "formula_evaluated": (im.get("quality") or {}).get("formula_evaluated", 0),
        "formula_passed": (im.get("quality") or {}).get("formula_passed", 0),
        "formula_failed": (im.get("quality") or {}).get("formula_failed", 0),
        "formula_pass_rate": (im.get("quality") or {}).get("formula_pass_rate"),
        "sign_normalizations": (im.get("quality") or {}).get("sign_normalizations", 0),
        "cashflow_sector": cf["sector"], "cashflow_method": cf["method"], "cashflow_status": cm.get("status"),
        "cashflow_scope_start": (cm.get("parser") or {}).get("scope_start"), "cashflow_scope_end": (cm.get("parser") or {}).get("scope_end"),
        "cashflow_scope_score": (cm.get("parser") or {}).get("scope_score"),
        "cashflow_patterns": ";".join((cm.get("parser") or {}).get("patterns", [])),
        "cashflow_input_rows": cmp.get("input_rows", 0), "cashflow_mapped_rows": cmp.get("mapped_rows", 0),
        "cashflow_unmapped_rows": cmp.get("unmapped_rows", 0), "cashflow_mapping_rate": cmp.get("mapping_rate", 0.0),
        "cashflow_value_nodes": cm.get("value_nodes", 0), "cashflow_current_nodes": cm.get("current_value_nodes", 0),
        "cashflow_previous_nodes": cm.get("previous_value_nodes", 0),
        "cashflow_formula_evaluated": (cm.get("quality") or {}).get("formula_evaluated", 0),
        "cashflow_formula_passed": (cm.get("quality") or {}).get("formula_passed", 0),
        "cashflow_formula_failed": (cm.get("quality") or {}).get("formula_failed", 0),
        "cashflow_formula_pass_rate": (cm.get("quality") or {}).get("formula_pass_rate"),
        "financial_position_status": fp["metrics"].get("status"),
        "financial_position_value_nodes": fp["metrics"].get("value_nodes", 0),
        "financial_position_current_nodes": fp["metrics"].get("current_value_nodes", 0),
        "financial_position_previous_nodes": fp["metrics"].get("previous_value_nodes", 0),
        "financial_position_recovered_rows": (fp["metrics"].get("parser") or {}).get("recovered_rows", 0),
        "income_source_recovered_rows": (im.get("parser") or {}).get("source_recovered_rows", 0),
        "cashflow_source_recovered_rows": (cm.get("parser") or {}).get("source_recovered_rows", 0),
        "cashflow_source_recovery_filled_nodes": (cm.get("parser") or {}).get("source_recovery_filled_nodes", 0),
        "financial_position_canonical_file": fp.get("canonical_file"),
        "comparison_file": merged_path.name if merged_path is not None else None,
        "canonical_file": income_path.name if income_path is not None and inc["canonical"] is not None else None,
        "cashflow_canonical_file": cashflow_path.name if cashflow_path is not None and cf["canonical"] is not None else None,
        "notes_status": (
            "parsed" if notes_ir is not None and (notes_ir.get("diagnostics") or {}).get("notes_found")
            else ("not_detected" if enable_notes else "disabled")
        ),
        "notes_sections": ((notes_ir or {}).get("diagnostics") or {}).get("section_count", 0),
        "notes_tables": ((notes_ir or {}).get("diagnostics") or {}).get("table_count", 0),
        "notes_rows": ((notes_ir or {}).get("diagnostics") or {}).get("row_count", 0),
        "notes_exported_rows": notes_rows_export.get("row_count", 0) if enable_notes else 0,
        "notes_rows_csv": (
            f"notes_rows/{notes_rows_export.get('csv_file')}"
            if audit_dir is not None and enable_notes and notes_rows_export.get("csv_file") else None
        ),
        "notes_links": ((notes_ir or {}).get("diagnostics") or {}).get("link_count", 0),
        "notes_ir_file": (
            notes_path.name
            if notes_path is not None
            and notes_ir is not None
            and (notes_ir.get("diagnostics") or {}).get("notes_found")
            else None
        ),
        "production": production,
    }


def main():
    """Điều phối một lần chạy production từ input Markdown đến manifest.

    Đầu vào:
    - tham số dòng lệnh gồm input, output, năm tùy chọn, sector, Notes và audit.

    Xử lý:
    - chọn source Markdown;
    - tạo output ngoài cây input;
    - gọi ``process_one`` cho từng báo cáo;
    - dọn artifact stale và ghi report JSON cùng ``manifest.json``.

    Đầu ra:
    - các file production trong ``<output>/reports``;
    - ``manifest.json`` mô tả batch;
    - mã thoát lỗi nếu input hoặc một bước bắt buộc không hợp lệ.
    """
    ap = argparse.ArgumentParser(
        description="Source-only mapper: Financial Position + Income + Cash Flow + additive Notes IR."
    )
    ap.add_argument("input", help="Markdown file or folder")
    ap.add_argument("--output", default="comparison_v9")
    ap.add_argument(
        "--current-year",
        type=int,
        default=None,
        help="Optional explicit current reporting year; otherwise infer per Markdown report.",
    )
    ap.add_argument(
        "--previous-year",
        type=int,
        default=None,
        help="Optional explicit comparative year; otherwise infer per Markdown report.",
    )
    ap.add_argument("--sector", choices=["auto", "bank", "enterprise", "securities", "insurance"], default="auto",
                    help="Income override only; Cash Flow sector is independently detected from its own scope.")
    ap.add_argument(
        "--notes",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable/disable v22.5 additive Notes IR extraction. Primary statements remain authoritative.",
    )
    ap.add_argument(
        "--audit",
        action="store_true",
        help="Also write rich parser/evaluation artifacts under <output>/audit/.",
    )
    ap.add_argument(
        "--same-label-recovery",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Enable hierarchy-aware recovery for parent/child rows with the "
            "same label. Use --no-same-label-recovery to roll back to the "
            "baseline behavior."
        ),
    )
    ap.add_argument(
        "--schema-profile",
        choices=sorted(SCHEMA_PROFILES),
        default="schema_v1_7",
        help=(
            "Schema bundle to use. schema_v1_7 enables the reversible BSI "
            "schema additions; use --schema-profile baseline to roll back."
        ),
    )
    args = ap.parse_args()

    schema_profile = SCHEMA_PROFILES[args.schema_profile]

    input_path = Path(args.input)
    output_dir = Path(args.output)
    try:
        md_files = select_md_files(input_path)
        ensure_output_is_outside_input(input_path, output_dir)
    except Exception as e:
        print(f"[FATAL] {e}", file=sys.stderr)
        raise SystemExit(2)

    output_dir.mkdir(parents=True, exist_ok=True)
    clear_legacy_output(output_dir)
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    audit_dir = output_dir / "audit" if args.audit else None
    if audit_dir is not None:
        audit_dir.mkdir(parents=True, exist_ok=True)
        prune_stale_report_artifacts(audit_dir, {stem_base(path) for path in md_files})
    fp_parser = FinancialPositionSourceParser(
        schema_path=schema_profile["financial_position_schema"],
        aliases_path=schema_profile["financial_position_aliases"],
        same_label_recovery=args.same_label_recovery,
    )
    print("[FINANCIAL_POSITION] source=markdown")

    if audit_dir is not None:
        write_json(
            audit_dir / "run_metadata.json",
            {
                "schema_version": "financial_parser_run_metadata_v1",
                "input": str(input_path.resolve()),
                "output": str(output_dir.resolve()),
                "current_year": args.current_year,
                "previous_year": args.previous_year,
                "period_resolution": "per_report_inferred_or_cli_override",
                "input_policy": "markdown_source_only",
                "source_reports": len(md_files),
                "same_label_recovery": args.same_label_recovery,
                "schema_profile": args.schema_profile,
                "financial_position_schema": str(schema_profile["financial_position_schema"]),
                "cash_flow_schema": str(schema_profile["cash_flow_schema"]),
                "preserve_decimal_branch_rows": schema_profile["preserve_decimal_branch_rows"],
            },
        )

    rows = []
    production_reports = []
    for p in md_files:
        try:
            year_resolution = infer_report_year_pair(
                p.read_text(encoding="utf-8-sig", errors="replace"),
                source_name=p.name,
                current_year=args.current_year,
                previous_year=args.previous_year,
            )
            r = process_one(
                p,
                audit_dir,
                year_resolution["current_year"],
                year_resolution["previous_year"],
                args.sector,
                fp_parser=fp_parser,
                enable_notes=args.notes,
                year_resolution=year_resolution,
                cashflow_schema_path=schema_profile["cash_flow_schema"],
                cashflow_aliases_path=schema_profile["cash_flow_aliases"],
                preserve_decimal_branch_rows=schema_profile["preserve_decimal_branch_rows"],
            )
            production = r.pop("production")
            source = production["report"]["source"]
            write_json(
                reports_dir / report_filename(
                    source["name"],
                    source["sha256"],
                ),
                production,
            )
            production_reports.append(production)
            rows.append(r)
            print(
                f"[OK] {p.name}: fp={r['financial_position_status']} nodes={r['financial_position_value_nodes']} "
                f"| income={r['status']} {r['mapped_rows']}/{r['input_rows']} "
                f"| cashflow={r['cashflow_status']} {r['cashflow_mapped_rows']}/{r['cashflow_input_rows']} "
                f"sector={r['cashflow_sector']} method={r['cashflow_method']}"
            )
        except Exception as e:
            rows.append({"source_name": p.name, "status": "error", "cashflow_status": "error", "error": repr(e)})
            print(f"[ERROR] {p.name}: {e}", file=sys.stderr)

    if not rows:
        print("[FATAL] Internal invariant failed: discovered Markdown files but produced zero summary rows.", file=sys.stderr)
        raise SystemExit(3)

    prune_stale_production_reports(
        reports_dir,
        {
            report_filename(
                report["report"]["source"]["name"],
                report["report"]["source"]["sha256"],
            )
            for report in production_reports
        },
    )

    errors = [r for r in rows if r.get("status") == "error"]
    manifest = {
        "contract": {
            "name": BATCH_SCHEMA_NAME,
            "version": BATCH_SCHEMA_VERSION,
        },
        "report_contract": {
            "name": OUTPUT_SCHEMA_NAME,
            "version": OUTPUT_SCHEMA_VERSION,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input": {
            "name": input_path.name,
            "policy": "markdown_source_only",
        },
        "options": {
            "current_year": args.current_year,
            "previous_year": args.previous_year,
            "sector": args.sector,
            "notes_enabled": args.notes,
            "schema_profile": args.schema_profile,
        },
        "report_count": len(production_reports),
        "error_count": len(errors),
        "reports": [manifest_entry(report) for report in production_reports],
    }
    if audit_dir is not None:
        manifest["audit"] = {"enabled": True, "directory": "audit"}
    write_json(output_dir / "manifest.json", manifest)
    print(f"\nManifest: {output_dir / 'manifest.json'}")

    if audit_dir is not None:
        write_json(audit_dir / "comparison_summary.json", rows)
        cols = [
            "source_name","source_sha256","current_year","previous_year","year_resolution","sector","status","scope_start","scope_end","scope_score","sector_method","patterns",
            "input_rows","mapped_rows","unmapped_rows","mapping_rate","income_value_nodes","income_current_nodes",
            "income_previous_nodes","current_coverage","previous_coverage","formula_evaluated","formula_passed",
            "formula_failed","formula_pass_rate","sign_normalizations",
            "cashflow_sector","cashflow_method","cashflow_status","cashflow_scope_start","cashflow_scope_end","cashflow_scope_score",
            "cashflow_patterns","cashflow_input_rows","cashflow_mapped_rows","cashflow_unmapped_rows","cashflow_mapping_rate",
            "cashflow_value_nodes","cashflow_current_nodes","cashflow_previous_nodes","cashflow_formula_evaluated",
            "cashflow_formula_passed","cashflow_formula_failed","cashflow_formula_pass_rate",
            "financial_position_status","financial_position_value_nodes","financial_position_current_nodes",
            "financial_position_previous_nodes","financial_position_recovered_rows",
            "income_source_recovered_rows","cashflow_source_recovered_rows","cashflow_source_recovery_filled_nodes",
            "financial_position_canonical_file",
            "comparison_file","canonical_file","cashflow_canonical_file",
            "notes_status","notes_sections","notes_tables","notes_rows","notes_exported_rows","notes_rows_csv","notes_links","notes_ir_file","error"
        ]
        with (audit_dir / "comparison_summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(r)
        print(f"Audit summary: {audit_dir / 'comparison_summary.csv'}")

    if errors:
        print(
            f"[FATAL] run rejected: errors={len(errors)}",
            file=sys.stderr,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
