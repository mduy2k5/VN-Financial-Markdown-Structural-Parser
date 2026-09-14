# v17 debug update

v17 continues the debug-oriented three-statement pipeline. It does **not** add a quality gate.

## Changes

1. Income formula validation is separated from extraction/mapping status.
   - `status` describes extraction/mapping coverage.
   - `validation_status` is `ok` or `formula_warning`.
   - Formula warnings no longer turn an otherwise complete mapping into `value_semantic_conflict`.
2. Enterprise sign handling is formula-only.
   - Canonical values remain faithful to source presentation.
   - Deductive enterprise rows are interpreted as magnitudes only inside formula validation.
   - Diagnostics record `canonical_mutated: false`.
3. Securities income aliases are expanded for FVTPL, margin/loan, brokerage variants.
4. Insurance income schema is expanded with premium, reinsurance, claims, and reserve-change rows before aliases are added.
   - This avoids creating aliases that point to nonexistent nodes.
5. Cash-flow aliases are enriched only for nodes that already exist in the schema (`PROVISIONS`, `UNREALIZED_FX`, selected securities working-capital rows).

## Important

The earlier proposal that normalizing enterprise cost rows to positive values would automatically make all 9 formula-conflict files `ok` is not assumed. The existing enterprise validator already uses magnitude semantics for COGS, other expense, and current tax. v17 therefore preserves source values and makes formula diagnostics independent from mapping status.
