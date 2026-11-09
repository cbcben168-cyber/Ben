"""Restart-safe history paths. No discovery, network access, or archive writes."""
import hashlib
import json
import os
from pathlib import Path

REQUIRED = ('ICT_V04_HISTORY', 'ICT_V04_DB', 'ICT_EXPERIMENT_DB',
            'ICT_FUTU_DAILY_ARCHIVE', 'ICT_FUTU_DAILY_ROOT')
OPTIONAL = ('ICT_FUTU_HOURLY_ARCHIVE', 'ICT_DAILY_ARCHIVE', 'ICT_DAILY_UPDATE_ROOT')


def load_config(root, config=None):
    path = Path(config or os.environ.get('ICT_HISTORY_CONFIG') or Path(root)/'data/history-runtime.json').resolve()
    if not path.is_file():
        raise ValueError('历史数据配置缺失：请先安装并核验 data/history-runtime.json；禁止回退旧历史数据。')
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        raise ValueError('历史数据配置无法读取或不是有效JSON。') from None
    if (not isinstance(value, dict) or set(value) != {'format', 'paths'}
            or value['format'] != 'ICT_HISTORY_RUNTIME_V1' or not isinstance(value['paths'], dict)):
        raise ValueError('历史数据配置格式未支持。')
    raw = value['paths']
    if set(raw) - set(REQUIRED + OPTIONAL):
        raise ValueError('历史数据配置包含未支持的字段；仅允许历史资料路径。')
    resolved = {}
    for key in REQUIRED + OPTIONAL:
        name = raw.get(key)
        if name is None and key in OPTIONAL:
            continue
        if not isinstance(name, str) or not name.strip():
            raise ValueError('历史数据配置缺少路径：'+key)
        resolved[key] = str((path.parent/name).resolve())
    for key in REQUIRED:
        target = Path(resolved[key])
        exists = target.is_dir() if key == 'ICT_FUTU_DAILY_ROOT' else target.is_file()
        if not exists:
            raise ValueError('历史数据路径缺失或类型错误：'+key+'；禁止回退旧历史数据。')
    from .futu_update import FutuVersions
    try:
        current, _ = FutuVersions(resolved['ICT_FUTU_DAILY_ARCHIVE'], resolved['ICT_FUTU_DAILY_ROOT']).current()
        if not current.is_file():
            raise ValueError()
    except (KeyError, TypeError, ValueError, OSError):
        raise ValueError('Futu日K版本指针或当前档案无效；禁止回退基准或旧历史数据。') from None
    signature = hashlib.sha256(json.dumps(resolved, sort_keys=True).encode('utf-8')).hexdigest()
    return dict(config=str(path), paths=resolved, sha256=signature)


def activate_config(root, config=None):
    result = load_config(root, config)
    for key in REQUIRED + OPTIONAL:
        os.environ.pop(key, None)
    os.environ.update(result['paths'])
    os.environ['ICT_HISTORY_CONFIG'] = result['config']
    return result
