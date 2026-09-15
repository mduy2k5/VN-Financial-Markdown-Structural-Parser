# Báo cáo triển khai v23.1.0 Structural Notes Extraction

## Baseline
v23.0.1 Notes Scope + row export.

## Vấn đề thực tế
- ABB trước đây chỉ ra 3 row và nhầm header/unit thành data.
- ACB chỉ đọc 13 row từ một matrix.
- ANV ra 0 row vì Notes chủ yếu là bullet/plain OCR structure.

## Kết quả v23.1
Sau structural parser + conservative noise guard:

| Corpus | Notes found | Rows |
|---|---:|---:|
| 57 BCTC | 57/57 | 27,542 |

| File | Trước v23.1 | v23.1 |
|---|---:|---:|
| ABB | 3 | 567 |
| ACB | 13 | 307 |
| ANV | 0 | 419 |

## Release gates
- 15/15 Notes tests PASS.
- Scope detection remains 57/57.
- No change to PRIMARY > NOTES policy.
- No mutation/overwrite of B01/B02/B03 canonical.
- No arithmetic scaling from unit detection.

## Lưu ý
27,542 là structural rows, chưa phải universal canonical rows. Một số multi-axis/OCR structures vẫn cần dimension/link refinement ở phiên bản sau.
