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
                        qfq=p['responses']['QFQ']['records'],
                        raw=p['responses']['NONE']['records'],
                        actions=p['rehab']['records']) for p in payloads])


def archive_identity(path):
    with closing(sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True)) as db:
        captures = {symbol: json.loads(raw) for symbol, raw in db.execute('SELECT symbol,payload FROM captures')}
    if set(captures) != {'US.' + ticker for ticker in TICKERS}:
        raise ValueError('旧版Futu档案未覆盖23只证券')
    return payload_identity([captures['US.' + ticker] for ticker in TICKERS])


def publish_capture(versions, capture_dir, target, progress=None, token=None):
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
        if progress:
            progress(23, '正在原子发布完整历史版本')
        previous = versions.pointer_data()['current']
        result = dict(status='SUCCESS', completed=23,
                    added_days=len(CAL.sessions_in_range(
                        str(CAL.next_session(pd.Timestamp(old['last'])).date()), target))
                    if target > old['last'] else 0,
                    current=dict(path=str(destination), version=name, symbols=23,
                                 first=old['first'], last=target, valuation_date=payloads[0]['valuation_date']),
                    previous=previous, token=token, message='历史行情更新成功。')
        _atomic_json(versions.pointer, dict(current=name, previous=previous, result=result))
        return result
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def finish_status(versions, result, token):
    # A per-task receipt and the committed pointer survive a status.json failure.
    receipt = versions.root / ('result_' + token + '.json')
    _atomic_json(receipt, result)
    try:
        _atomic_json(versions.status, result)
    except OSError:
        result = dict(result, status_warning='状态文件写入失败；结果已保存在任务回执中。')
        _atomic_json(receipt, result)
        return result
    return result


def task_status(versions):
    from .futu_task import task_guard
    with task_guard(versions.root) as owned:
        status = read_json(versions.status)
        if not owned:
            return True, status
        lock = read_json(versions.lock)
        if not lock and versions.lock.exists():
            versions.lock.unlink()  # Only while owning the OS guard.
            status = dict(status='FAILED', completed=0, reason='任务记录损坏，已安全释放，可重新执行。')
        if lock and time.time() - lock.get('created', 0) < 15:
            return True, status
        if lock:
            token = lock.get('token', '')
            receipt = read_json(versions.root / ('result_' + token + '.json'))
            committed = versions.pointer_data().get('result', {})
            if committed.get('token') == token:
                receipt = committed
            status = receipt or dict(status='FAILED', completed=0,
                                     reason='更新进程已异常退出，请重新执行。', token=token)
            try:
                _atomic_json(versions.status, status)
            except OSError:
                pass
            versions.lock.unlink(missing_ok=True)
        if status.get('status') == 'RUNNING':
            token = status.get('token', '')
            committed = versions.pointer_data().get('result', {})
            status = (committed if committed.get('token') == token else
                      read_json(versions.root / ('result_' + token + '.json'))) or dict(
                          status='FAILED', completed=0, reason='更新进程已结束但没有完整结果，请重试。')
        return False, status


def start_update(versions, script, python=sys.executable):
    from .futu_task import task_guard
    with task_guard(versions.root) as owned:
        if not owned:
            return False
        lock = read_json(versions.lock)
        if lock and time.time() - lock.get('created', 0) < 15:
            return False
        token = uuid.uuid4().hex
        _atomic_json(versions.lock, dict(created=time.time(), token=token))
        try:
            _atomic_json(versions.status, dict(status='RUNNING', phase='正在连接本地Futu OpenD',
                                               completed=0, token=token))
            subprocess.Popen([str(python), str(script), '--baseline', str(versions.baseline),
                              '--root', str(versions.root), '--token', token],
                             cwd=Path(script).resolve().parents[1],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            return True
        except Exception:
            versions.lock.unlink(missing_ok=True)
            finish_status(versions, dict(status='FAILED', completed=0,
                                        reason='无法启动本地历史更新进程。', token=token), token)
            raise


def run_update(versions, capture_script, now=None, capture_dir=None, token=None):
    """Controller runs in a separate process; only capture_script imports Futu SDK."""
    token = token or uuid.uuid4().hex
    current = versions.summary()
    target = latest_completed(now or datetime.now(timezone.utc))
    stage = versions.root / ('capture_' + token)
    progress_file = versions.root / 'capture_progress.json'
    _atomic_json(versions.status, dict(status='RUNNING', phase='正在重新获取23只证券的完整日K',
                                      completed=0, target=target, token=token))
    try:
        if capture_dir is None:
            subprocess.run([sys.executable, str(capture_script), '--output', str(stage),
                            '--start', current['first'], '--end', target,
                            '--progress', str(progress_file)], check=True,
                           timeout=TIMEOUT_SECONDS)
            capture_dir = stage
        def progress(count, phase):
            _atomic_json(versions.status, dict(status='RUNNING', phase=phase,
                                               completed=count, target=target, token=token))
        progress(0, '校验完整QFQ及复权事件')
        result = publish_capture(versions, capture_dir, target, progress, token)
        result['token'] = token
        result['capture_dir'] = str(capture_dir)
        return finish_status(versions, result, token)
    except subprocess.TimeoutExpired:
        reason = 'Futu OpenD响应超时，请检查连接后重试。'
    except subprocess.CalledProcessError as exc:
        reason = f'Futu OpenD抓取进程异常退出（退出码{exc.returncode}）；请查看任务日志核对连接、权限或数据错误。'
    except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
        reason = '历史行情校验或发布失败：' + str(exc)
    finally:
        try:
            progress_file.unlink(missing_ok=True)
        except OSError:
            pass  # Raw captures are retained for audit, including failed attempts.
    committed = versions.pointer_data().get('result', {})
    if committed.get('token') == token:
        return finish_status(versions, dict(committed, status_warning='版本已发布；后续结果记录失败，已恢复发布结果。'), token)
    result = dict(status='FAILED', phase='失败', completed=0, target=target, reason=reason)
    result['token'] = token
    return finish_status(versions, result, token)
