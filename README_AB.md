# v0.5.1 A/B: v0.5 baseline + P1-P34 conservative enrichment

## Strategy

The `bullet` engine is now a **hybrid**, not a replacement mapper:

1. Run the original v0.5 pipeline and create its canonical FINANCIAL_POSITION result.
2. Run `BulletDebugFlow` P1-P34 on the detected statement range.
3. Map bullet rows with the existing v1.6 schema/aliases.
4. Bullet results may fill only missing `current`, `previous`, or `note` slots.
5. Existing v0.5 values are never overwritten. Conflicts are logged as `keep_v05_conflict`.

This preserves v0.5 precision while using the new structural engine to recover missing data.

## Commands

```powershell
# Hybrid (default): v0.5 canonical + P1-P34 fill-missing enrichment
python .\run_ab.py .\input --output .\output_ab

# Original v0.5 only
python .\run_ab.py .\input --engine v05 --output .\output_ab

# Run both and create side-by-side comparison JSON
python .\run_ab.py .\input --compare --output .\output_ab
```

Useful optional switches:

```powershell
--fuzzy
--allow-unknown-structure
--financial-schema <path>
--financial-aliases <path>
--guide <path>
```

## Output

With `--compare`:

- `output_ab/bullet/`: hybrid result
- `output_ab/v05/`: untouched v0.5 result
- `output_ab/comparison/<file>.comparison.json`: per-file comparison
- `output_ab/comparison_summary.json`: all files

Hybrid debug files include:

- `bullet_flow.json`
- `bullet_extracted_rows.json`
- `bullet_enrichment.json`
- `hybrid_stats.json`

## Mapping scope

The existing canonical resource pack currently covers FINANCIAL_POSITION/B02 and bank OFF_BALANCE. The P1-P34 engine also extracts INCOME_STATEMENT and CASH_FLOW structurally, but those two are not canonical-mapped until dedicated schema/alias packs are supplied.
