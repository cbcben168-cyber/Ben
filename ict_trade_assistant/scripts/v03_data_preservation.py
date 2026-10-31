"""只读比较本轮SQLite备份与现有库；不恢复、不覆盖任何记录。"""
from pathlib import Path
import sqlite3
import json
import hashlib

ROOT=Path(__file__).resolve().parents[1]
TABLES=('notes','plan_versions','settings','events','acknowledgements')


def main():
    out=ROOT/'data/v03_acceptance'
    before=sqlite3.connect((out/'user-before.sqlite3').as_uri()+'?mode=ro',uri=True)
    after=sqlite3.connect((ROOT/'data/desk.sqlite3').as_uri()+'?mode=ro',uri=True)
    report={}
    try:
        for table in TABLES:
            old=before.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
            current=after.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
            digest=lambda rows:hashlib.sha256(json.dumps(rows,ensure_ascii=False).encode()).hexdigest()
            row=dict(before_rows=len(old),after_rows=len(current),before_sha256=digest(old),after_sha256=digest(current),
                     unchanged=old==current,all_original_rows_preserved=all(r in current for r in old))
            if table=='events':
                added=[r for r in current if r not in old]
                row['added_event_kinds']=[dict(id=r[0],at=r[1],kind=r[2],symbol=r[3]) for r in added]
                row['only_system_events_added']=all(r[2] in ('SYSTEM_HEALTH','DATA_HEALTH') for r in added)
            report[table]=row
    finally:
        before.close();after.close()
    result=dict(tables=report,all_original_rows_preserved=all(r['all_original_rows_preserved'] for r in report.values()),
                user_fields_unchanged=all(report[t]['unchanged'] for t in TABLES if t!='events'),
                only_system_events_added=report['events']['only_system_events_added'])
    (out/'user-preservation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='tables'}))
    assert result['all_original_rows_preserved'] and result['user_fields_unchanged'] and result['only_system_events_added']


if __name__=='__main__':main()
