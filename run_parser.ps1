param(
    [Parameter(Mandatory=$true)]
    [string]$InputPath,

    [string]$OutputPath = ".\output_flat_v0_4"
)

python -m flat_parser.cli `
  $InputPath `
  --schema ".\resources\universal_financial_position_schema_v1_1.json" `
  --aliases ".\resources\universal_financial_position_aliases_v1_1.json" `
  --guide ".\resources\universal_structural_guide_a1_a5.json" `
  --output $OutputPath
