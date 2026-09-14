# v16 — Structural Identity Repair

V16 is a debug iteration built from v15. It does **not** add a quality gate and does not suppress low-accuracy outputs.

## Main changes

### Financial Position

- Adds structural row identity based on `label + form_code + hierarchy context` instead of collapsing rows by label alone.
- Supports column-major OCR/LLM layouts where a row is emitted as `label -> code -> note? -> current -> previous`.
- Supports continuation-page rows using `Số cuối năm / Số đầu năm` with optional unit annotations.
- Supports `Số liệu / Số liệu (Trình bày lại)` bank layouts.
- Supports inline `value (2025), value (2024)` layouts and `Tổng cộng` rows whose real identity is the parent label.
- Extracts trailing/suffix form codes such as `(200)` and `(Mã số: 311, Thuyết minh: 20)`.
- Keeps repeated generic labels such as `Nguyên giá` separated by hierarchy context.

### Cash Flow

- Adds section-aware source recovery (`operating`, `investing`, `financing`, `reconciliation`).
- Adds `current inline + Năm trước child` recovery for continuation pages.
- Adds `Năm kết thúc 31/12/YYYY` period-section recovery.
- Adds label-less statutory pipe-table recovery by form code. A code table can only fill an existing unique semantic node for the active sector/method and only when that period is null.
- Never overwrites an existing non-null semantic value.

### Reconciliation

- Source observations are never deleted.
- Reconciliation groups Financial Position observations using hierarchy context.
- Reconciled values live in `reconciled_source_view`; original source-observation values are not synthetically modified.
- Semantic hydration remains fill-missing-only.

### Income

Income broad extraction/mapping remains frozen from v15.

## Debug diagnostics

Look at:

- `diagnostics.source_statement_recovery`
- `diagnostics.source_observation_reconciliation`
- `diagnostics.form_code_period_recovery`
- `parent_label`
- `hierarchy_path`
- `duplicate_group_id`

Accuracy is a measurement for debugging, not a runtime gate.

## Run

```powershell
python .\run_income_comparison.py .\output\md_reports `
  --financial-position-dir .\<financial_position_canonical_dir> `
  --comparison-dir .\comparison_v15 `
  --output .\comparison_v16 `
  --current-year 2025 `
  --previous-year 2024
```

## v16.1 refinements from detailed v15 evaluation

The detailed v15 evaluation showed that row recall alone was not the dominant Financial Position problem: many matched rows still had wrong current/previous values. v16.1 therefore adds a conservative period-identity repair before source-row recovery.

- `31/12/current_year`, `Số cuối năm`, `Cuối kỳ` => current.
- `31/12/previous_year`, `Số đầu năm`, `Đầu kỳ` => previous.
- **`01/01/current_year` / `Ngày 1 tháng 1 năm current_year` => previous**, even though the calendar year is the current report year.
- Existing semantic values are corrected only when explicit period-label evidence has a unique consensus. Conflicting evidence is retained in diagnostics instead of being guessed.
- Short/generic Financial Position labels such as `Nguyên giá`, `Hao mòn lũy kế`, `Dự phòng`, `Tổng cộng` keep their literal source observation and additionally receive a hierarchy-qualified contextual observation for evaluator/downstream matching.

New diagnostic:

`diagnostics.financial_position_period_identity_repair`
