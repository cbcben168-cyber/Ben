"""本次前台、有界只读监测；不启动、终止或恢复任何服务。"""
import argparse
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=3600)
    parser.add_argument('--url', default='http://127.0.0.1:8501')
    parser.add_argument('--output', type=Path, default=Path('data/v03_acceptance/soak.jsonl'))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    began = time.monotonic()
    with args.output.open('w', encoding='utf-8', buffering=1) as out:
        while True:
            row = dict(at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=round(time.monotonic()-began, 3))
            try:
                with urllib.request.urlopen(args.url+'/_stcore/health', timeout=3) as response:
                    row['health'] = response.read().decode()
                runtime = json.loads(Path('data/runtime.json').read_text(encoding='utf-8'))
                row.update(runtime=runtime, heartbeat_age_seconds=round(time.time()-runtime['at'], 3))
            except Exception as exc:
                row['error'] = type(exc).__name__ + ': ' + str(exc)
            out.write(json.dumps(row, ensure_ascii=False)+'\n')
            if row['elapsed_seconds'] >= args.seconds:
                break
            time.sleep(min(10, args.seconds-row['elapsed_seconds']))
    print(json.dumps(dict(实际秒数=row['elapsed_seconds'],证据=str(args.output)), ensure_ascii=False))


if __name__ == '__main__':
    main()
