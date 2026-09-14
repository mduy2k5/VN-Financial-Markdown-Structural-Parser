from __future__ import annotations
import argparse, csv, json
from pathlib import Path


def classify(r):
    sector=r.get('sector')
    rows=int(r.get('input_rows') or 0)
    mapped=int(r.get('mapped_rows') or 0)
    vals=int(r.get('income_value_nodes') or r.get('value_nodes') or 0)
    cur=int(r.get('income_current_nodes') or r.get('current_value_nodes') or 0)
    prev=int(r.get('income_previous_nodes') or r.get('previous_value_nodes') or 0)
    rate=float(r.get('mapping_rate') or 0)
    status=str(r.get('status') or '')
    if status.startswith('schema_sector_gap:') or sector in {'securities'}:
        return 'SCHEMA_SECTOR_GAP'
    if sector in {None,'','unknown'}:
        return 'UNKNOWN_SECTOR'
    if rows == 0:
        return 'NO_STRUCTURAL_ROWS'
    if vals == 0:
        return 'NO_MAPPED_VALUES'
    if rate < 0.8:
        return 'LOW_MAPPING_COVERAGE'
    if cur and not prev:
        return 'MISSING_PREVIOUS_PERIOD'
    if vals and (cur/vals < .75 or prev/vals < .75):
        return 'PARTIAL_PERIODS'
    if rate < .95:
        return 'PARTIAL_MAPPING'
    return 'OK'


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('summary_json')
    ap.add_argument('--output',default='income_failure_report.csv')
    args=ap.parse_args()
    rows=json.loads(Path(args.summary_json).read_text(encoding='utf-8'))
    out=[]
    for r in rows:
        x=dict(r); x['failure_class']=classify(r); out.append(x)
    cols=['source_name','sector','status','failure_class','scope_start','scope_end','input_rows','mapped_rows','unmapped_rows','mapping_rate','income_value_nodes','income_current_nodes','income_previous_nodes','financial_position_preserved']
    with Path(args.output).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore'); w.writeheader(); w.writerows(out)
    counts={}
    for x in out: counts[x['failure_class']]=counts.get(x['failure_class'],0)+1
    print(json.dumps(counts,ensure_ascii=False,indent=2))
    print(args.output)

if __name__=='__main__': main()
