"""Click-triggered supervisor; one OS lock and one bounded owned process tree."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desk.futu_update import FutuVersions, run_update, read_json, finish_status
from desk.futu_task import task_guard, bounded_worker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--token', required=True)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--timeout', type=float, default=600, help=argparse.SUPPRESS)
    args = parser.parse_args()
    versions = FutuVersions(args.baseline, args.root)
    if args.worker:
        if sys.stdin.readline().strip() != 'GO':
            return 2
        result = run_update(versions, ROOT / 'scripts/capture_futu_daily.py', token=args.token)
        return 0 if result['status'] != 'FAILED' else 1
    with task_guard(versions.root, wait=15) as owned:
        if not owned or read_json(versions.lock).get('token') != args.token:
            return 2
        try:
            command = [sys.executable, str(Path(__file__).resolve()), '--baseline', str(args.baseline),
                       '--root', str(args.root), '--token', args.token, '--worker']
            with (versions.root / ('task_' + args.token + '.log')).open('wb') as log:
                code = bounded_worker(command, min(600, max(.1, args.timeout)), log)
            receipt = read_json(versions.root / ('result_' + args.token + '.json'))
            if not receipt:
                raise RuntimeError('worker_exit_' + str(code))
            return 0 if receipt['status'] != 'FAILED' else 1
        except Exception as exc:
            committed = versions.pointer_data().get('result', {})
            if committed.get('token') == args.token:
                result = dict(committed, status_warning='版本已发布；后续状态记录异常，已从发布指针恢复结果。')
            else:
                phase = read_json(versions.status).get('phase', '启动')
                reason = ('完整更新流程超时：' + phase if isinstance(exc, subprocess.TimeoutExpired)
                          else ('更新子进程异常退出（' + str(exc) + '）：' + phase
                                if isinstance(exc, RuntimeError) else '无法启动或监控更新进程：' + phase))
                result = dict(status='FAILED', completed=0, reason=reason, token=args.token)
            finish_status(versions, result, args.token)
            return 0 if result['status'] == 'SUCCESS' else 1
        finally:
            if read_json(versions.lock).get('token') == args.token:
                versions.lock.unlink(missing_ok=True)


if __name__ == '__main__':
    raise SystemExit(main())
