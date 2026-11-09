"""Catch loss of source configuration across a clean service restart."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def configured(tmp_path):
    paths = {
        'ICT_V04_HISTORY': 'data/history.json',
        'ICT_V04_DB': 'data/user.sqlite3',
        'ICT_EXPERIMENT_DB': 'data/experiments.sqlite3',
        'ICT_FUTU_DAILY_ARCHIVE': 'data/day.sqlite3',
        'ICT_FUTU_DAILY_ROOT': 'data/versions',
        'ICT_FUTU_HOURLY_ARCHIVE': 'data/hourly',
    }
    for key, value in paths.items():
        p = tmp_path / value
        p.parent.mkdir(parents=True, exist_ok=True)
        if key.endswith('ROOT') or key.endswith('HOURLY_ARCHIVE'):
            p.mkdir()
        else:
            p.write_text('{}', encoding='utf-8')
    config = tmp_path / 'history-runtime.json'
    config.write_text(json.dumps(dict(format='ICT_HISTORY_RUNTIME_V1', paths=paths)))
    return config, paths


def check(config, inherited=None):
    # A new process gets no inherited ICT paths, exactly as after a desktop restart.
    env = {k: v for k, v in os.environ.items() if not k.startswith('ICT_')}
    env.update(inherited or {})
    return subprocess.run([sys.executable, '-B', '-X', 'utf8', str(ROOT/'scripts/run_server.py'),
                           '--history', '--config', str(config), '--check-history-config'],
                          cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8')


def test_clean_restarts_restore_same_sources(configured):
    config, paths = configured
    a, b = check(config), check(config)
    assert a.returncode == b.returncode == 0, a.stderr
    first, second = json.loads(a.stdout), json.loads(b.stdout)
    assert first == second
    assert first['paths'] == {k: str((config.parent/v).resolve()) for k, v in paths.items()}
    assert len(first['sha256']) == 64


def test_missing_config_cannot_use_legacy_environment(tmp_path):
    result = check(tmp_path/'missing.json', {'ICT_V04_HISTORY': str(tmp_path/'old.json')})
    assert result.returncode != 0
    assert '历史数据配置缺失' in result.stderr
    assert not (tmp_path/'data').exists()


def test_missing_daily_archive_stops_before_creating_user_db(configured):
    config, paths = configured
    before = (config.parent/paths['ICT_V04_DB']).read_bytes()
    (config.parent/paths['ICT_FUTU_DAILY_ARCHIVE']).unlink()
    result = check(config)
    assert result.returncode != 0
    assert 'ICT_FUTU_DAILY_ARCHIVE' in result.stderr
    assert 'Traceback' not in result.stderr
    assert (config.parent/paths['ICT_V04_DB']).read_bytes() == before


def test_missing_user_db_is_not_recreated(configured):
    config, paths = configured
    user = config.parent/paths['ICT_V04_DB']
    user.unlink()
    result = check(config)
    assert result.returncode != 0
    assert 'ICT_V04_DB' in result.stderr
    assert not user.exists()


def test_persisted_paths_override_stale_inherited_paths(configured):
    config, _ = configured
    result = check(config, {'ICT_FUTU_DAILY_ARCHIVE': 'wrong-old.sqlite3',
                            'ICT_FUTU_HOURLY_ARCHIVE': 'wrong-old-hourly'})
    assert result.returncode == 0, result.stderr
    paths = json.loads(result.stdout)['paths']
    assert paths['ICT_FUTU_DAILY_ARCHIVE'] == str((config.parent/'data/day.sqlite3').resolve())
    assert paths['ICT_FUTU_HOURLY_ARCHIVE'] == str((config.parent/'data/hourly').resolve())


def test_invalid_version_pointer_cannot_fall_back_to_baseline(configured):
    config, paths = configured
    (config.parent/paths['ICT_FUTU_DAILY_ROOT']/'current.json').write_text('{"current":"futu_missing.sqlite3"}')
    result = check(config)
    assert result.returncode != 0
    assert '版本' in result.stderr


def test_missing_hourly_does_not_block_daily_startup(configured):
    config, paths = configured
    (config.parent/paths['ICT_FUTU_HOURLY_ARCHIVE']).rmdir()
    result = check(config)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['paths']['ICT_FUTU_DAILY_ARCHIVE'].endswith('day.sqlite3')


def test_config_rejects_unknown_settings_without_exposing_values(configured):
    config, paths = configured
    paths['API_KEY'] = 'sensitive-test-placeholder'
    config.write_text(json.dumps(dict(format='ICT_HISTORY_RUNTIME_V1', paths=paths)))
    result = check(config)
    assert result.returncode != 0
    assert '未支持' in result.stderr
    assert 'sensitive-test-placeholder' not in result.stdout + result.stderr


@pytest.mark.parametrize('stale,missing,trend,want', [
    (False, False, '下跌', '历史趋势可分析'),
    (True, False, '上涨', '历史资料已过期'),
    (False, False, 'UNKNOWN', '历史样本不足'),
    (False, True, 'UNKNOWN', '暂无已验收历史资料'),
])
def test_summary_distinguishes_historical_analysis_from_execution(monkeypatch, stale, missing, trend, want):
    from desk import dashboard_cards
    rendered = []
    monkeypatch.setattr(dashboard_cards.st, 'markdown', lambda text, **kw: rendered.append(text))
    dashboard_cards.summary('SPY', dict(trend=trend, volatility='正常'), stale, missing,
                            '2026-11-06 16:00 纽约', False)
    html = ''.join(rendered)
    assert want in html
    assert '实时交易资格关闭' in html
    if trend != 'UNKNOWN' and not missing:
        assert ('↓ 偏空' if trend == '下跌' else '↑ 偏多') in html
    assert '继续等待' not in html
