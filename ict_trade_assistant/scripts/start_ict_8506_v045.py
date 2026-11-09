"""Manual 8506 recovery entry. Does not stop services or register startup items."""
import argparse
from pathlib import Path
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.futu_daily_runtime import load_config, launch_environment


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--start', action='store_true', help='Default validates without starting a service')
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if not args.start:
            print('8506 runtime configuration valid; no service started.')
            return 0
        # Refuse every occupied port, including another instance of this app.
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 8506))
        env = launch_environment(config)
        with (ROOT / 'data/v045-launch-out.log').open('ab') as out, \
                (ROOT / 'data/v045-launch-error.log').open('ab') as err:
            process = subprocess.Popen([config['python'], '-B', str(ROOT / 'scripts/run_server.py'),
                                        '--history', '--port', '8506'], cwd=ROOT, env=env,
                                       stdout=out, stderr=err,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print('8506 launch requested; verify heartbeat, build, paths and health before acceptance. Wrapper PID:', process.pid)
        return 0
    except Exception as exc:
        print('8506 launch refused: ' + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
