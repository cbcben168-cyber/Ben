"""Explicit, non-secret runtime profile shared by the scheduler and 8506 launcher."""
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
ENV_KEYS = {'ICT_V04_DB', 'ICT_V04_HISTORY', 'ICT_EXPERIMENT_DB',
            'ICT_DAILY_ARCHIVE', 'ICT_DAILY_UPDATE_ROOT',
            'ICT_FUTU_DAILY_ARCHIVE', 'ICT_FUTU_DAILY_ROOT'}
ENGINE_FILES = {'app.py', 'desk/futu_update.py', 'desk/futu_task.py',
                'desk/futu_update_ui.py', 'scripts/capture_futu_daily.py',
                'scripts/import_futu_daily.py', 'scripts/update_futu_daily.py',
                'scripts/v04_history_fixture.py'}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_config(path):
    config = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    expected = {'schema', 'app_root', 'python', 'environment', 'baseline_sha256',
                'engine_sha256', 'build_sha256', 'unattended_enabled',
                'real_new_day_accepted', 'vendor_finality_accepted'}
    if set(config) != expected or config['schema'] != 'ICT_FUTU_DAILY_RUNTIME_V1':
        raise ValueError('Invalid runtime profile schema')
    root = Path(config['app_root'])
    python = Path(config['python'])
    if not root.is_absolute() or root.resolve() != ROOT or not python.is_absolute() or not python.is_file():
        raise ValueError('Runtime root or interpreter does not match this installation')
    env = config['environment']
    if set(env) != ENV_KEYS:
        raise ValueError('Runtime profile must explicitly set or unset all seven path variables')
    for key, value in env.items():
        if value is None and key in {'ICT_DAILY_ARCHIVE', 'ICT_DAILY_UPDATE_ROOT'}:
            continue
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError('Runtime paths must be absolute')
        item = Path(value).resolve()
        if not item.is_relative_to(root.resolve() / 'data'):
            raise ValueError('Runtime data path escapes the installation')
        if not item.exists():
            raise ValueError('Configured runtime data path is missing: ' + key)
    baseline = Path(env['ICT_FUTU_DAILY_ARCHIVE']).resolve()
    versions = Path(env['ICT_FUTU_DAILY_ROOT']).resolve()
    protected = {Path(env[key]).resolve() for key in
                 ('ICT_V04_DB', 'ICT_V04_HISTORY', 'ICT_EXPERIMENT_DB')}
    if (len(protected) != 3 or not all(p.is_file() for p in protected)
            or not baseline.is_file() or not versions.is_dir() or baseline in protected):
        raise ValueError('Invalid baseline or version directory')
    if any(p.is_relative_to(versions) for p in {*protected, baseline}):
        raise ValueError('Version directory overlaps protected input data')
    if sha256(baseline) != config['baseline_sha256']:
        raise ValueError('Baseline hash changed')
    if set(config['engine_sha256']) != ENGINE_FILES:
        raise ValueError('Incomplete accepted engine manifest')
    if any(sha256(root / name) != value for name, value in config['engine_sha256'].items()):
        raise ValueError('Accepted engine file changed')
    sources = [root / 'app.py', root / 'scripts/run_server.py', *sorted((root / 'desk').glob('*.py'))]
    if hashlib.sha256(b''.join(p.read_bytes() for p in sources)).hexdigest() != config['build_sha256']:
        raise ValueError('Accepted service build changed')
    for key in ('unattended_enabled', 'real_new_day_accepted', 'vendor_finality_accepted'):
        if type(config[key]) is not bool:
            raise ValueError('Acceptance switches must be explicit booleans')
    return config


def launch_environment(config, inherited=None):
    env = dict(os.environ if inherited is None else inherited)
    # Unknown ICT settings are not carried from a terminal into a restored service.
    for key in list(env):
        if key.upper().startswith('ICT_'):
            env.pop(key)
    for key, value in config['environment'].items():
        if value is not None:
            env[key] = value
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return env


def require_unattended(config):
    if not all(config[k] for k in
               ('unattended_enabled', 'real_new_day_accepted', 'vendor_finality_accepted')):
        raise ValueError('Unattended execution is disabled; real-new-day and vendor-finality acceptance required')


def check_opend():
    """Called only in an owned, bounded child; never serialize the global response."""
    import logging
    import logging.handlers
    from unittest.mock import patch
    with patch.object(logging.handlers, 'TimedRotatingFileHandler',
                      lambda *a, **k: logging.NullHandler()):
        from futu import OpenQuoteContext, SysConfig, RET_OK
        SysConfig.set_all_thread_daemon(True)
        SysConfig.enable_console_log(False)
        quote = OpenQuoteContext(host='127.0.0.1', port=11111)
        try:
            ret, state = quote.get_global_state()
            return bool(ret == RET_OK and state.get('qot_logined') is True)
        finally:
            quote.close()


def bounded_login(config, log, timeout=30):
    from desk.futu_task import bounded_worker
    return bounded_worker([config['python'], '-B', str(ROOT / 'scripts/futu_daily_runtime.py'),
                           '--login-worker'], timeout, log) == 0


if __name__ == '__main__':
    if sys.argv[1:] != ['--login-worker'] or sys.stdin.readline().strip() != 'GO':
        raise SystemExit(2)
    try:
        raise SystemExit(0 if check_opend() else 3)
    except Exception:
        # Neither credentials nor the raw global-state response enter logs.
        raise SystemExit(3)
