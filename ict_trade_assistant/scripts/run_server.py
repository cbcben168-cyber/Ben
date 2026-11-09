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
    parser.add_argument('--port', type=int, default=8506)
    parser.add_argument('--history', action='store_true', help='使用本地历史入口，不连接OpenD')
    parser.add_argument('--config', help='持久化历史路径配置；默认 data/history-runtime.json')
    parser.add_argument('--check-history-config', action='store_true', help='只读校验配置，不启动服务')
    args = parser.parse_args()
    if args.port == 8501:
        parser.error('v0.4隔离开发禁止使用8501；请保留v0.3服务')
    history_config = None
    if args.config or args.check_history_config:
        if not args.history:
            parser.error('历史配置仅用于 --history 入口')
    if args.history:
        from desk.history_runtime import activate_config
        try:
            history_config = activate_config(ROOT, args.config)
        except ValueError as exc:
            parser.error(str(exc))
        if args.check_history_config:
            print(json.dumps(history_config, ensure_ascii=False))
            return 0
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
                    uptime_seconds=round(time.monotonic()-began), root=str(ROOT), build_sha256=build,
                    history_config_sha256=history_config['sha256'] if history_config else None)), encoding='utf-8')
                temp.replace(target)
            except Exception:
                log.exception('心跳记录失败')
            stop.wait(10)

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        from streamlit.web import cli
        entry = ROOT / ('scripts/v04_history_fixture.py' if args.history else 'app.py')
        sys.argv = ['streamlit', 'run', str(entry), '--server.headless=true',
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
