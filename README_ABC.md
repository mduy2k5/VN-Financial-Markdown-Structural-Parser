# So sánh 3 engine: v0.5 / flow / hybrid

## Ba chế độ

- `v05`: parser 0.5 nguyên bản.
- `flow`: P1-P34 structural flow + bộ mapping hiện có, hoàn toàn độc lập với canonical của v0.5.
- `hybrid`: canonical của v0.5 làm nền; flow chỉ fill slot còn thiếu và không overwrite conflict.

## Chạy từng engine

```powershell
python .\run_ab.py .\input --engine v05 --output .\output_abc
python .\run_ab.py .\input --engine flow --output .\output_abc
python .\run_ab.py .\input --engine hybrid --output .\output_abc
```

## Chạy cả 3

```powershell
python .\run_ab.py .\input --compare-all --output .\output_abc
```

Output:

```text
output_abc/
  v05/
  flow/
  hybrid/
  comparison/
  comparison_summary.json
  comparison_summary.csv
```

`comparison_summary.csv` có số canonical value-node của cả ba engine và so sánh pairwise:

- `v05_vs_flow`
- `v05_vs_hybrid`
- `flow_vs_hybrid`

Trong từng JSON comparison còn có danh sách canonical node có giá trị khác nhau để review precision, không chỉ nhìn coverage.
