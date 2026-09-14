# Unified runner modes

`run.py` is the production entrypoint. It can run one parser independently or run the hybrid.

## Run v0.5 only

```powershell
python .\run.py .\input --mode v05 --output .\output_v05
```

## Run Flow only

```powershell
python .\run.py .\input --mode flow --output .\output_flow
```

## Run Hybrid

```powershell
python .\run.py .\input --mode hybrid --output .\output_hybrid
```

Hybrid policy is unchanged: v0.5 remains authoritative and Flow only enriches/fills missing canonical slots according to the existing hybrid implementation.

## Compare all three

```powershell
python .\run.py .\input --mode compare --output .\output_compare
```

## One file instead of a folder

```powershell
python .\run.py .\input\ABB_BCTC_2025_hop_nhat_kiem_toan.md --mode hybrid --output .\output_abb
```

## Output contract

Single-engine run:

```text
output_x/
├── run_manifest.json
├── run_summary.json
├── run_summary.csv
└── <engine>/
    └── ... normal integrated output files ...
```

Compare mode:

```text
output_compare/
├── run_manifest.json
├── v05/
├── flow/
├── hybrid/
├── comparison/
├── comparison_summary.json
└── comparison_summary.csv
```

The legacy `run_ab.py` remains available and unchanged for backwards compatibility.
