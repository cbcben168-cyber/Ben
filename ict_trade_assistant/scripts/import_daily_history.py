"""Import one saved vendor daily response; no network or user-database access."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from desk.history_import import DailyArchive


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--symbol',required=True)
    parser.add_argument('--archive',type=Path,default=ROOT/'data/v042/history.sqlite3')
    args=parser.parse_args()
    saved=json.loads(args.input.read_text(encoding='utf-8-sig'))
    payload=saved.get('response',saved)
    acquired=saved.get('acquired_at') or datetime.fromtimestamp(args.input.stat().st_mtime,timezone.utc).isoformat()
    result=DailyArchive(args.archive).import_payload(payload,args.symbol,acquired)
    print(json.dumps(result,ensure_ascii=True))


if __name__=='__main__':
    main()
