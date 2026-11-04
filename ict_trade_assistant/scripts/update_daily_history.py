"""Standalone local market-data updater. No Codex/MCP/Trading API dependency."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from desk.daily_update import LocalAlpaca, probe_local, run_update, make_plan
from desk.history_import import DailyArchive
from datetime import datetime, timezone


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe',action='store_true')
    parser.add_argument('--dry-run',action='store_true',help='只生成缺失计划，不查询供应商；不代表自动任务验收')
    args=parser.parse_args();root=ROOT/'data/v043'
    if args.probe:
        report=probe_local(root)
    else:
        with sqlite3.connect((ROOT/'data/v04/desk.sqlite3').as_uri()+'?mode=ro',uri=True) as c:
            saved=dict(c.execute('SELECT key,value FROM settings'))
        entries=json.loads(saved['watchlist_entries'])
        legacy=json.loads((ROOT/'data/v04/history.json').read_text(encoding='utf8'))
        base=DailyArchive(ROOT/'data/v042/history.sqlite3')
        if args.dry_run:
            report=dict(status='DRY_RUN_PLAN_ONLY',rows=make_plan(entries,legacy,base,DailyArchive(root/'updates.sqlite3'),datetime.now(timezone.utc)),unattended_proven=False)
        else:report=run_update(root,entries,legacy,base)
    print(json.dumps(report,ensure_ascii=True))
    return 0 if report['status'] in ('COMPLETE','PASS','DRY_RUN_PLAN_ONLY') else 2


if __name__=='__main__':raise SystemExit(main())
