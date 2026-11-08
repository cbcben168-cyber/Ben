"""Explicitly isolated Streamlit entry. Refuses production paths."""
import os
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
state = Path(os.environ['ICT_HISTORY_RECOVERY_PREVIEW_ROOT']).resolve()
if not state.is_relative_to((ROOT/'.local').resolve()):
    raise RuntimeError('历史恢复预览只允许工作区.local内的独立副本')
files = dict(ICT_V04_DB='user.sqlite3', ICT_V04_HISTORY='history.json',
             ICT_EXPERIMENT_DB='experiments.sqlite3', ICT_DAILY_ARCHIVE='alpaca.sqlite3',
             ICT_FUTU_DAILY_ARCHIVE='futu_qfq_20261106.sqlite3')
for key, name in files.items():
    path = state/name
    if not path.is_file() or path.is_symlink():
        raise RuntimeError('预览副本不完整或不是独立文件：'+name)
    os.environ[key] = str(path)
if not (state/'v043/updates.sqlite3').is_file():
    raise RuntimeError('缺少独立v043副本')
os.environ['ICT_DAILY_UPDATE_ROOT'] = str(state/'v043')
runpy.run_path(str(ROOT/'scripts/v04_history_fixture.py'), run_name='__main__')
