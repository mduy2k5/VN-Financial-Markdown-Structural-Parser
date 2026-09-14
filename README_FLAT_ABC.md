# v0.5.2 Flat A/B/C

Three engines:
- v05: original parser 0.5
- flow: flat-row P1-P34 extraction + existing aliases/schema
- hybrid: v0.5 canonical + safe fill from the same flat-row flow

Source hierarchy is not used by the mapper. Indentation remains only where individual extraction patterns need local structural ownership.

Run:
```powershell
python .\run_ab.py .\input --compare-all --output .\output_abc
```
