"""Isolated Futu capture publication. The dashboard only reads these files."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid

import pandas as pd

from .daily_update import latest_completed
from .futu_daily import FutuDailyArchive, canonical, digest
from .clock import CAL

TICKERS = ('SPY', 'QQQ', 'IWM', 'SOXX', 'SMH', 'VOO', 'IVV', 'VTI', 'VEA', 'VUG',
           'IEFA', 'VTV', 'SPYM', 'BND', 'VXUS', 'IEMG', 'VGT', 'GLD', 'AGG', 'IWF',
           'IJH', 'VWO', 'XLK')
TIMEOUT_SECONDS = 600


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(canonical(value), encoding='utf-8')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class FutuVersions:
    def __init__(self, baseline, root=None):
        self.baseline = Path(baseline).resolve()
        self.root = Path(root).resolve() if root else self.baseline.parent / 'futu_versions'
        self.pointer = self.root / 'current.json'
        self.status = self.root / 'status.json'
        self.lock = self.root / 'update.lock'

    def _path(self, name):
        if name == 'baseline':
            return self.baseline
        if not isinstance(name, str) or not name.startswith('futu_') or name != Path(name).name or not name.endswith('.sqlite3'):
            raise ValueError('历史版本指针无效')
        path = (self.root / name).resolve()
        if path.parent != self.root or not path.is_file():
            raise ValueError('历史版本文件缺失')
        return path

    def pointer_data(self):
        if not self.pointer.exists():
            return dict(current='baseline', previous=None)
        value = json.loads(self.pointer.read_text(encoding='utf-8'))
        self._path(value['current'])
        return value

    def current(self):
        value = self.pointer_data()
        return self._path(value['current']), value['current']

    def summary(self, validate=False):
        path, version = self.current()
        archive = FutuDailyArchive(path)
        if validate:
            rows = [archive.read('US.' + ticker) for ticker in TICKERS]
            metas = [row[0] for row in rows if row]
        else:
            with closing(archive.connect()) as db:
                rows = db.execute('SELECT s.symbol,c.verification FROM series s '
                                  'JOIN captures c ON c.sha256=s.capture_sha').fetchall()
            metas = [json.loads(row[1]) for row in rows]
        if len(rows) != len(TICKERS) or len(metas) != len(TICKERS):
            raise ValueError('当前历史档案未覆盖23只证券')
        if not validate and {symbol for symbol, _ in rows} != {'US.' + t for t in TICKERS}:
            raise ValueError('当前历史档案证券不完整')
        if len({(m['first'], m['last'], m['valuation_date']) for m in metas}) != 1:
            raise ValueError('当前历史档案的日期或复权估值日期不一致')
        return dict(path=str(path), version=version, symbols=len(rows),
                    first=metas[0]['first'], last=metas[0]['last'],
                    valuation_date=metas[0]['valuation_date'])

    def rollback(self):
        pointer = self.pointer_data()
        previous = pointer.get('previous')
        if not previous:
            raise ValueError('没有可回滚的前一版本')
        self._path(previous)
        _atomic_json(self.pointer, dict(current=previous, previous=pointer['current']))
        return self.summary()


def payload_identity(payloads):
    """Exclude capture timestamps while retaining provider version and full price basis."""
    return digest([dict(symbol=p['symbol'], sdk_version=p['sdk_version'],
                        valuation_date=p['valuation_date'],
                        qfq=p['responses']['QFQ']['records'],
                        raw=p['responses']['NONE']['records'],
                        actions=p['rehab']['records']) for p in payloads])


def archive_identity(path):
    with closing(sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True)) as db:
        captures = {symbol: json.loads(raw) for symbol, raw in db.execute('SELECT symbol,payload FROM captures')}
    if set(captures) != {'US.' + ticker for ticker in TICKERS}:
        raise ValueError('旧版Futu档案未覆盖23只证券')
    return payload_identity([captures['US.' + ticker] for ticker in TICKERS])


def publish_capture(versions, capture_dir, target, progress=None):
    """Validate every symbol before creating or switching a complete archive."""
    from scripts.import_futu_daily import load_capture

    old = versions.summary(validate=True)
    payloads = load_capture(capture_dir, old['first'], target)
    identity = payload_identity(payloads)
    if identity == archive_identity(old['path']):
        return dict(status='UP_TO_DATE', completed=23, added_days=0,
                    current=old, message='历史行情已经是最新，无需更新。')
    if target < old['last']:
        raise ValueError('新数据比现有历史档案更旧')
    stage = versions.root / ('stage_' + uuid.uuid4().hex)
    stage.mkdir(parents=True, exist_ok=False)
    candidate = stage / 'candidate.sqlite3'
    try:
        archive = FutuDailyArchive.create(candidate)
        for index, payload in enumerate(payloads, 1):
            archive.import_payload(payload)
            if progress:
                progress(index, '校验完整QFQ及复权事件')
        for ticker in TICKERS:
            archive.read('US.' + ticker)
        if archive_identity(candidate) != identity:
            raise ValueError('候选历史版本复核失败')
        name = 'futu_' + target.replace('-', '') + '_' + identity[:16] + '.sqlite3'
        destination = versions.root / name
        if destination.exists():
            if archive_identity(destination) != identity:
                raise ValueError('已有版本文件内容冲突')
        else:
            os.replace(candidate, destination)
        previous = versions.pointer_data()['current']
        _atomic_json(versions.pointer, dict(current=name, previous=previous))
        return dict(status='SUCCESS', completed=23,
                    added_days=len(CAL.sessions_in_range(
                        str(CAL.next_session(pd.Timestamp(old['last'])).date()), target))
                    if target > old['last'] else 0,
                    current=versions.summary(), previous=previous,
                    message='历史行情更新成功。')
    finally:
        shutil.rmtree(stage)


def _process_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def start_update(versions, script, python=sys.executable):
    """Reserve one task before spawning the local controller process."""
    versions.root.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(versions.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            lock = json.loads(versions.lock.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return False
        if _process_alive(lock.get('pid')) or time.time() - lock.get('created', 0) < 15:
            return False
        versions.lock.unlink()
        return start_update(versions, script, python)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        token = uuid.uuid4().hex
        json.dump(dict(pid=None, created=time.time(), token=token), stream)
    try:
        _atomic_json(versions.status, dict(status='RUNNING', phase='正在连接本地Futu OpenD', completed=0))
        command = [str(python), str(script), '--baseline', str(versions.baseline),
                   '--root', str(versions.root), '--token', token]
        process = subprocess.Popen(command, cwd=Path(script).resolve().parents[1],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            with versions.lock.open('r+', encoding='utf-8') as stream:
                lock = json.load(stream)
                if lock.get('token') == token:
                    lock['pid'] = process.pid
                    stream.seek(0)
                    json.dump(lock, stream)
                    stream.truncate()
        except FileNotFoundError:
            pass  # The controller already finished and released this task.
        return True
    except Exception:
        try:
            _atomic_json(versions.status, dict(status='FAILED', completed=0,
                                               reason='无法启动本地历史更新进程。'))
        finally:
            versions.lock.unlink(missing_ok=True)
        raise


def run_update(versions, capture_script, now=None, capture_dir=None):
    """Controller runs in a separate process; only capture_script imports Futu SDK."""
    current = versions.summary()
    target = latest_completed(now or datetime.now(timezone.utc))
    stage = versions.root / ('capture_' + uuid.uuid4().hex)
    progress_file = versions.root / 'capture_progress.json'
    _atomic_json(versions.status, dict(status='RUNNING', phase='正在重新获取23只证券的完整日K',
                                      completed=0, target=target))
    try:
        if capture_dir is None:
            subprocess.run([sys.executable, str(capture_script), '--output', str(stage),
                            '--start', current['first'], '--end', target,
                            '--progress', str(progress_file)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=TIMEOUT_SECONDS)
            capture_dir = stage
        def progress(count, phase):
            _atomic_json(versions.status, dict(status='RUNNING', phase=phase,
                                               completed=count, target=target))
        result = publish_capture(versions, capture_dir, target, progress)
        _atomic_json(versions.status, result)
        return result
    except subprocess.TimeoutExpired:
        reason = 'Futu OpenD响应超时，请检查连接后重试。'
    except subprocess.CalledProcessError:
        reason = 'Futu获取失败或权限不足，请检查OpenD连接和历史行情权限。'
    except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
        reason = '历史行情校验或发布失败：' + str(exc)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        progress_file.unlink(missing_ok=True)
    result = dict(status='FAILED', phase='失败', completed=0, target=target, reason=reason)
    _atomic_json(versions.status, result)
    return result
