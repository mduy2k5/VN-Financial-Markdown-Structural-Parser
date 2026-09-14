# Alias-first + Regex Fallback Flow (v0.5.5)

## Mục tiêu

Giữ legacy/alias mapper làm nguồn mapping chính. Regex chỉ chạy khi mapper chính không chọn được candidate.
Regex fallback không cạnh tranh với một alias match đã thành công.

## Luồng

```text
Normalized row / structural node
        |
        v
Legacy alias mapper
        |
        +-- selected ----------------------> accept legacy mapping
        |
        `-- no selected
                |
                v
        strict regex fallback
                |
                +-- high confidence + non-ambiguous --> accept regex_fallback
                |                                 |
                |                                 `--> collect alias candidate
                |
                `-- weak / ambiguous ------------> unresolved / review
```

## Guard của regex fallback

- Không dùng fuzzy để auto-map.
- Top score phải >= 0.93.
- Nếu có runner-up, score gap phải >= 0.08.
- Các label mơ hồ như `Nguyên giá` thường giữ trạng thái unresolved thay vì tự map.
- Provenance được ghi dưới dạng `regex_fallback_*`.

## Chạy production với fallback

```powershell
python .\run.py .\input `
  --mode hybrid `
  --mapping-strategy legacy `
  --regex-fallback `
  --collect-alias-candidates `
  --output .\output
```

Chạy Flow riêng:

```powershell
python .\run.py .\input --mode flow --regex-fallback --output .\output_flow
```

Chạy v0.5 riêng:

```powershell
python .\run.py .\input --mode v05 --regex-fallback --output .\output_v05
```

Tắt fallback:

```powershell
python .\run.py .\input --mode hybrid --no-regex-fallback --output .\output_legacy
```

## So sánh legacy với fallback

```powershell
python .\run.py .\input --mode fallback-compare --output .\output_fallback_compare
```

Output chính:

```text
fallback_comparison.csv
fallback_comparison.json
alias_candidates.csv
alias_candidates.json
```

## Alias discovery

Mỗi regex fallback thành công được ghi vào `alias_candidates.json` và aggregate theo:

- source_label
- node_id
- canonical_name
- số lần xuất hiện
- số file
- engine
- method
- max confidence

Các candidate xuất hiện lặp lại ở nhiều file và không conflict có thể được review rồi promote vào alias pack.

## Mapping strategies vẫn hỗ trợ

- `legacy`: mapper cũ.
- `regex`: regex-only, dùng cho benchmark/thử nghiệm.
- `alias-regex-fallback`: alias-first rồi regex fallback.

`--regex-fallback` khi đi cùng strategy mặc định `legacy` sẽ tự chọn `alias-regex-fallback`.
