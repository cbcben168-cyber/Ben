"""记录生命周期与心跳；不自动重启。隔离测试可指定端口。"""
from pathlib import Path
import argparse
import sys, os, json, threading, time, faulthandler, hashlib
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run_entry(entry, log):
    try:
        entry()
    except SystemExit as exc:
        if exc.code not in (None, 0):
            log.exception('服务异常退出 pid=%s code=%s', os.getpid(), exc.code)
            raise
        return 0
    except KeyboardInterrupt:
        log.info('收到正常中断 pid=%s', os.getpid())
        return 0
    except BaseException:
        log.exception('服务入口未处理异常 pid=%s', os.getpid())
        raise
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8501)
    args = parser.parse_args()
    from desk.diagnostics import initialize
    log = initialize(ROOT)
    suffix = '' if args.port == 8501 else '-' + str(args.port)
    fatal = (ROOT / ('data/fatal' + suffix + '.log')).open('a', encoding='utf-8')
    faulthandler.enable(fatal)
    stop = threading.Event()
    began = time.monotonic()
    sources = [ROOT / 'app.py', Path(__file__).resolve()] + sorted((ROOT / 'desk').glob('*.py'))
    build = hashlib.sha256(b''.join(p.read_bytes() for p in sources)).hexdigest()
    log.info('服务启动 pid=%s port=%s root=%s sha256=%s', os.getpid(), args.port, ROOT, build)

    def heartbeat():
        while not stop.is_set():
            try:
                target = ROOT / ('data/runtime' + suffix + '.json')
                temp = target.with_suffix('.tmp')
                temp.write_text(json.dumps(dict(pid=os.getpid(), port=args.port, at=time.time(),
                    uptime_seconds=round(time.monotonic()-began), root=str(ROOT), build_sha256=build)), encoding='utf-8')
                temp.replace(target)
            except Exception:
                log.exception('心跳记录失败')
            stop.wait(10)

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        from streamlit.web import cli
        sys.argv = ['streamlit', 'run', str(ROOT / 'app.py'), '--server.headless=true',
                    '--server.address=127.0.0.1', '--server.port=' + str(args.port), '--server.fileWatcherType=none']
        return run_entry(cli.main, log)
    finally:
        stop.set()
        thread.join(timeout=2)
        log.info('服务入口退出 pid=%s port=%s uptime_seconds=%.3f', os.getpid(), args.port, time.monotonic()-began)
        faulthandler.disable()
        fatal.close()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
