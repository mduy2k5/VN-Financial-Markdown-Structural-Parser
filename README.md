# Financial Statement Parser

Python tools for extracting financial-position, off-balance, and income-statement
rows from Markdown financial reports. The project contains a legacy parser, a
structural flow parser, a hybrid parser, and a dedicated income comparison pipeline.

## Requirements

- Python 3.10 or newer
- Install test dependencies when running the test suite:

```powershell
python -m pip install -r .\requirements.txt
```

The repository intentionally does not contain source reports or generated results.
Keep those files under `output/`; that directory is ignored by Git.

## Main parser

`run.py` is the current unified entrypoint. It accepts one Markdown file or a folder.

```powershell
python .\run.py .\input --mode v05 --output .\output\v05
python .\run.py .\input --mode flow --output .\output\flow
python .\run.py .\input --mode hybrid --output .\output\hybrid
python .\run.py .\input --mode compare --output .\output\compare
```

The hybrid mode keeps the v0.5 canonical result authoritative and only fills missing
slots from the structural flow. Compare mode writes `v05/`, `flow/`, `hybrid/`,
`comparison/`, and a batch summary below the requested output directory.

Useful options include:

```powershell
python .\run.py .\input --mode compare --mapping-strategy regex --output .\output\compare_regex
python .\run.py .\input --mode mapping-compare --output .\output\mapping_compare
python .\run.py .\input --mode hybrid --no-hybrid-fill --output .\output\hybrid_no_fill
```

Use `--fuzzy` or `--allow-unknown-structure` only when the input requires them.
The active engine and mapping options are recorded in `run_manifest.json`.

## Income and cash-flow comparison

`run_income_comparison.py` extracts income statements and cash-flow statements,
detects their profiles, maps rows to the universal schemas, and merges the result
into an existing comparison JSON when one is available.

Recommended v12-debug run:

```powershell
python .\run_income_comparison.py .\output\md_reports `
  --financial-position-dir .\output\legacy\flow\statements\financial_position `
  --comparison-dir .\output\comparisons\comparison_v11 `
  --output .\output\comparisons\comparison_v12 `
  --current-year 2025 `
  --previous-year 2024
```

The command prints input discovery before processing and fails when the input path
does not exist or contains no Markdown files. It writes one canonical JSON per
successful income or cash-flow profile plus `comparison_summary.json` and
`comparison_summary.csv`.

Supported automatic sector profiles are `bank`, `enterprise`, `securities`, and
`insurance` for income. Cash Flow v1 currently maps enterprise and bank direct or
indirect profiles; unsupported special profiles remain diagnostic-only.

Cash Flow v2 adds broader row discovery, securities diagnostics, previous-period
recovery, and a coverage gate. v12 also preserves source observations and integrates
all three statement canonicals.
Identity is based on method, section, and normalized label. Form codes are supporting
evidence because bank forms reuse codes across sections. A `partial_mapping` or
`partial_source_coverage` status can therefore be more informative than the v9
`ok` status when v10 discovers additional source rows.

## Income row mapper

Use `run_income_map.py` when the input is already a CSV/JSON row export rather than
Markdown:

```powershell
python .\run_income_map.py .\rows `
  --sector auto `
  --output .\output\income_map `
  --current-year 2025 `
  --previous-year 2024
```

Runtime income schemas and aliases are in `resources/` and
`income_schema/resources/`. Do not replace them with generated reports.

## Integrated and legacy entrypoints

These wrappers remain available for existing workflows:

```powershell
python .\run_ab.py .\input --compare-all --output .\output\ab_compare
python .\run.py .\input --mode compare --output .\output\compare
.\run_parser.ps1 -InputPath .\input -OutputPath .\output\parser
.\run_integrated.ps1 -InputPath .\input -OutputPath .\output\integrated
```

Prefer `run.py` for new parser runs and `run_income_comparison.py` for the income
pipeline. The PowerShell wrappers are retained for compatibility.

## Tests

Run the full suite from the repository root:

```powershell
python -m pytest -q
```

For a dependency-free syntax check:

```powershell
python -m compileall -q flat_parser income_schema scripts tests `
  income_mapper.py income_observation_patch.py run_income_comparison.py
```

## Repository layout

```text
flat_parser/                 Parser engines and shared models
income_schema/               Standalone income row mapper
resources/                   Runtime schemas, aliases, and structural guides
samples/                     Small safe fixtures
scripts/                     Guide and coverage utilities
tests/                       Regression tests and fixtures
output/                      Local reports and generated results; ignored by Git
```

Design notes and detailed mode behavior are documented in:

- `RUN_MODES.md`
- `FEATURE_FLAGS.md`
- `REGEX_FALLBACK_FLOW.md`
- `STATEMENT_SCANNER_DESIGN.md`
