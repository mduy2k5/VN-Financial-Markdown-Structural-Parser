# Mapping strategies and feature flags

The parser now separates two independent choices:

1. Engine: `v05`, `flow`, `hybrid`
2. Mapping strategy: `legacy`, `regex`

Default behavior remains backward-compatible: `legacy` mapping and hybrid fill enabled.

## Run one engine with legacy mapper

```powershell
python .\run.py .\input --mode v05 --mapping-strategy legacy --output .\out_v05_legacy
python .\run.py .\input --mode flow --mapping-strategy legacy --output .\out_flow_legacy
python .\run.py .\input --mode hybrid --mapping-strategy legacy --output .\out_hybrid_legacy
```

## Run one engine with flat regex mapper

```powershell
python .\run.py .\input --mode v05 --mapping-strategy regex --output .\out_v05_regex
python .\run.py .\input --mode flow --mapping-strategy regex --output .\out_flow_regex
python .\run.py .\input --mode hybrid --mapping-strategy regex --output .\out_hybrid_regex
```

`regex` deliberately ignores source hierarchy/context during semantic mapping. It uses normalized label regex search against canonical names and aliases.

## Compare the three engines using one mapper

```powershell
python .\run.py .\input --mode compare --mapping-strategy legacy --output .\compare_legacy
python .\run.py .\input --mode compare --mapping-strategy regex --output .\compare_regex
```

## Compare regex back to legacy for all three engines

```powershell
python .\run.py .\input --mode mapping-compare --output .\mapping_compare
```

This runs six combinations:

- v05 + legacy
- v05 + regex
- flow + legacy
- flow + regex
- hybrid + legacy
- hybrid + regex

and creates:

- `mapping_strategy_comparison.csv`
- `mapping_strategy_comparison.json`
- `legacy/...`
- `regex/...`

## Feature switches

Hybrid fill can be disabled independently:

```powershell
python .\run.py .\input --mode hybrid --mapping-strategy regex --no-hybrid-fill
```

Fuzzy matching can be enabled/disabled independently:

```powershell
--fuzzy
--no-fuzzy
```

Unknown structural patterns can be enabled/disabled independently:

```powershell
--allow-unknown-structure
--no-allow-unknown-structure
```

All active features are recorded in `run_manifest.json`.
