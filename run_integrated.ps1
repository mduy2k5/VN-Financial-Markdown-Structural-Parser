param(
  [Parameter(Mandatory=$true)][string]$InputPath,
  [string]$OutputPath = ".\output_flat_v0_5"
)

python -m flat_parser.integrated_cli `
  $InputPath `
  --financial-schema ".\resources\universal_financial_position_schema_v1_6.json" `
  --financial-aliases ".\resources\universal_financial_position_aliases_v1_6_1.json" `
  --off-balance-schema ".\resources\universal_off_balance_bank_schema_v1_3.json" `
  --off-balance-aliases ".\resources\universal_off_balance_bank_aliases_v1_3.json" `
  --income-schema ".\income_schema\income_statement_schema_v1.json" `
  --income-aliases ".\income_schema\income_statement_aliases_v1.json" `
  --guide ".\resources\universal_structural_guide_a1_a5.json" `
  --output $OutputPath
