"""Click-triggered local controller. Never invoked by a page redraw or scheduler."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desk.futu_update import FutuVersions, run_update, _atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--token', required=True)
    args = parser.parse_args()
    versions = FutuVersions(args.baseline, args.root)
    try:
        try:
            result = run_update(versions, ROOT / 'scripts/capture_futu_daily.py')
            return 0 if result['status'] != 'FAILED' else 1
        except Exception:
            _atomic_json(versions.status, dict(status='FAILED', completed=0,
                                               reason='本地更新进程异常退出；旧版历史档案保持可用。'))
            return 1
    finally:
        try:
            lock = json.loads(versions.lock.read_text(encoding='utf-8'))
            if lock.get('token') == args.token:
                versions.lock.unlink()
        except (OSError, ValueError):
            pass


if __name__ == '__main__':
    raise SystemExit(main())
