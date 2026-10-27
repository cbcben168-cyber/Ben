"""D2 deterministic evidence primitives. No SDK, sockets, trading or scheduler imports."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import threading
import time
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXPECTED_ROOT = Path('C:/Users/cbcbe/.codex/worktrees/futu-factor-progress-dashboard-v1/Futu')
CONTRACT = HERE / 'WINDOW_CONTRACT.json'
CONTRACT_SHA = 'dabd95e01ce21b76d13047297b07e4f85bc36cbb657af8bab6486ac27f707b16'
SYMBOL = 'US.SPY'
SLOTS = ('connect', 'state', 'subscription_before', 'subscribe', 'subscription_after',
         'ticker_pull', 'book_pull', 'unsubscribe', 'close')
WINDOW = {'launch_start': '2026-10-27T17:14:00+00:00', 'launch_last': '2026-10-27T17:14:20+00:00', 'start': '2026-10-27T17:15:00+00:00', 'end': '2026-10-27T17:20:00+00:00', 'cleanup_end': '2026-10-27T17:20:10+00:00'}


class Stop(Exception):
    """Only constant reason codes reach evidence; arbitrary SDK messages never do."""


def require(ok, code):
    if not ok:
        raise Stop(code)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    return digest(Path(path).read_bytes())


def plain(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {'$float': str(value)}
    if isinstance(value, datetime):
        return {'$datetime': value.isoformat()}
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if type(value).__name__ in ('NAType', 'NaTType'):
        return {'$missing': type(value).__name__}
    if hasattr(value, 'item'):
        return plain(value.item())
    raise Stop('UNSUPPORTED_VALUE_TYPE')


def encoded(value):
    return json.dumps(plain(value), ensure_ascii=True, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def payload(value):
    if hasattr(value, 'columns') and hasattr(value, 'dtypes'):
        return {'kind': 'dataframe', 'columns': plain(list(value.columns)),
                'dtypes': [str(x) for x in value.dtypes], 'index': plain(list(value.index)),
                'data': plain(value.values.tolist())}
    return {'kind': 'value', 'value': plain(value)}


def utc(text):
    t = datetime.fromisoformat(text)
    require(t.tzinfo is not None, 'NAIVE_UTC')
    return t.astimezone(timezone.utc)


class Clock:
    def stamp(self):
        return {'utc': datetime.now(timezone.utc).isoformat(), 'monotonic_ns': time.monotonic_ns()}

    def sleep(self, seconds):
        time.sleep(seconds)


class Guard:
    def __init__(self, clock, window=None):
        self.clock, self.window = clock, window or WINDOW
        self.initial = clock.stamp()

    def check(self):
        s = self.clock.stamp()
        elapsed = (s['monotonic_ns'] - self.initial['monotonic_ns']) / 1e9
        wall = (utc(s['utc']) - utc(self.initial['utc'])).total_seconds()
        require(elapsed >= 0 and abs(wall - elapsed) <= 1, 'CLOCK_JUMP')
        require(elapsed < 370 and utc(s['utc']) < utc(self.window['cleanup_end']), 'HARD_DEADLINE')
        return s

    def launch(self):
        t = utc(self.check()['utc'])
        require(utc(self.window['launch_start']) <= t <= utc(self.window['launch_last']), 'LAUNCH_WINDOW')


@dataclass(frozen=True)
class Limits:
    records: int = 50_000
    market_bytes: int = 60 * 1024 * 1024
    total_bytes: int = 64 * 1024 * 1024
    message_bytes: int = 1024 * 1024
    queue_size: int = 1000


def write_once(path, data):
    path = Path(path)
    with path.open('xb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def atomic(path, obj):
    path = Path(path)
    temp = path.with_suffix('.tmp')
    with temp.open('wb') as f:
        f.write(encoded(obj)); f.flush(); os.fsync(f.fileno())
    os.replace(temp, path)


def control(folder, obj):
    with (Path(folder)/'CONTROL.jsonl').open('ab') as f:
        f.write(encoded(obj)+b'\n'); f.flush(); os.fsync(f.fileno())


def directory_bytes(folder):
    return sum(p.stat().st_size for p in Path(folder).rglob('*') if p.is_file())


class QualityError(Stop):
    """An INVALID envelope already durably recorded; safe to continue draining."""


class QualityPolicy:
    def __init__(self):
        data = (HERE/'POLICY.json').read_bytes()
        require(digest(data) == (HERE/'POLICY.sha256').read_text().strip(), 'POLICY_DRIFT')
        self.rules = json.loads(data)
        self.crossed = {'prewindow': 0, 'observation': 0}
        self.consecutive = {'prewindow': 0, 'observation': 0}

    def observe(self, stream, observation, reason=None):
        phase = 'observation' if observation else 'prewindow'
        if reason and reason != 'CROSSED_BOOK':
            raise QualityError(reason)
        if stream != 'ORDER_BOOK':
            return
        if reason:
            self.crossed[phase] += 1
            self.consecutive[phase] += 1
            rule = self.rules[phase]
            require(self.crossed[phase] <= rule['crossed_total'] and
                    self.consecutive[phase] < rule['crossed_consecutive'], 'CROSSED_BUDGET_EXCEEDED')
        else:
            self.consecutive[phase] = 0


class Inbox:
    def __init__(self, clock, limits=Limits()):
        require(limits.queue_size > 0, 'INVALID_QUEUE_BUDGET')
        self.clock, self.limits = clock, limits
        self.q = queue.Queue(limits.queue_size)
        self.fault = None
        self.lock = threading.Lock()
        self.sequence = 0
        self.accepting = True
        self.unstored = None
        self.received = self.accepted = self.rejected = self.after_close = self.peak = 0

    def close_reception(self):
        with self.lock:
            self.accepting = False

    def fail(self, code):
        with self.lock:
            if self.fault is None:
                self.fault = code

    def submit(self, stream, native, raw=None, proto_fields=None, origin='push',
               public=None, received=None, epoch=1):
        # Serialization, admission and close share one lock: no accepted-after-close race.
        with self.lock:
            self.received += 1
            if not self.accepting or self.fault is not None:
                self.after_close += 1
                return
            received = received or self.clock.stamp()
            raw_data = decoded = None
            try:
                raw_data = bytes(raw) if raw is not None else None
                decoded = encoded({'native': native, 'public': public, 'protobuf_fields': proto_fields})
                require(len(decoded) <= self.limits.message_bytes and
                        (raw_data is None or len(raw_data) <= self.limits.message_bytes), 'MESSAGE_LIMIT')
                self.sequence += 1
                envelope = dict(sequence=self.sequence, stream=stream, epoch=epoch, origin=origin,
                                received=received, decoded=decoded, raw=raw_data)
                self.q.put_nowait(envelope)
                self.accepted += 1
                self.peak = max(self.peak, self.q.qsize())
            except (queue.Full, Stop, Exception) as exc:
                code = ('QUEUE_LIMIT' if isinstance(exc, queue.Full) else
                        str(exc) if isinstance(exc, Stop) else 'CALLBACK_ENCODING_FAILED')
                self.rejected += 1
                self.unstored = {'reason': code, 'decoded_bytes': len(decoded) if decoded else None,
                    'decoded_sha256': digest(decoded) if decoded else None,
                    'raw_bytes': len(raw_data) if raw_data is not None else None,
                    'raw_sha256': digest(raw_data) if raw_data is not None else None}
                self.fault = self.fault or code
                self.accepting = False


def source_time(value, received, evidence, zone=None):
    result = {'raw': plain(value), 'utc': None, 'source_age_ms': None,
              'status': 'SOURCE_AGE_UNKNOWN', 'timeliness_pass': False}
    if value in (None, '', 0, '0') or zone is None:
        return result
    try:
        t = datetime.fromisoformat(str(value))
        if t.tzinfo is None:
            naive = t
            t = t.replace(tzinfo=ZoneInfo(zone), fold=0)
            require(t.utcoffset() == naive.replace(tzinfo=ZoneInfo(zone), fold=1).utcoffset(),
                    'AMBIGUOUS_SOURCE_TIME')
        result['utc'] = t.astimezone(timezone.utc).isoformat()
        if not evidence or evidence.get('qualified') is not True:
            return result
        age = (utc(received['utc']) - utc(evidence['observed_at_utc'])).total_seconds()
        bound = float(evidence['error_bound_seconds'])
        require(0 <= age <= 65 and abs(float(evidence['offset_seconds'])) <= 1 and
                0 <= bound <= 1, 'CLOCK_UNQUALIFIED')
        ms = (utc(received['utc']) - utc(result['utc'])).total_seconds() * 1000
        result.update(source_age_ms=ms, conservative_upper_ms=ms + bound * 1000,
                      status='KNOWN_SOURCE_AGE', timeliness_pass=(-bound * 1000 <= ms and ms + bound * 1000 <= 2000))
        if ms < -bound * 1000:
            result['status'] = 'NEGATIVE_AGE'
    except (ValueError, TypeError, KeyError, Stop, OverflowError):
        result['status'] = 'SOURCE_TIME_NOT_VERIFIED'
    return result


def inspect_market(stream, native, received, clock_evidence=None, book_zone=None):
    require(stream in ('TICKER', 'ORDER_BOOK'), 'UNAUTHORIZED_STREAM')
    rows = native if stream == 'TICKER' else [native]
    require(isinstance(rows, list) and bool(rows), 'EMPTY_MARKET_DATA')
    details = []
    for row in rows:
        require(isinstance(row, dict) and row.get('code') == SYMBOL, 'WRONG_SYMBOL_OR_SHAPE')
        if stream == 'TICKER':
            for name in ('price', 'volume', 'turnover'):
                v = row.get(name)
                require(isinstance(v, (int, float)) and not isinstance(v, bool) and
                        math.isfinite(v) and (v > 0 if name == 'price' else v >= 0), 'INVALID_TICKER')
            require(row.get('sequence') is not None, 'MISSING_TICKER_SEQUENCE')
            details.append({'time': source_time(row.get('time'), received, clock_evidence,
                                                'America/New_York'),
                            'direction_interpretation': 'UNVERIFIED_VENDOR_FIELD'})
        else:
            for side in ('Bid', 'Ask'):
                require(isinstance(row.get(side), list) and bool(row[side]), 'EMPTY_BOOK')
                for level in row[side]:
                    require(isinstance(level, (list, tuple)) and len(level) >= 3, 'INVALID_BOOK_LEVEL')
                    for i, v in enumerate(level[:3]):
                        require(isinstance(v, (int, float)) and not isinstance(v, bool) and
                                math.isfinite(v) and (v > 0 if i == 0 else v >= 0), 'INVALID_BOOK_LEVEL')
            bid, ask = row['Bid'][0][0], row['Ask'][0][0]
            require(bid <= ask, 'CROSSED_BOOK')
            details.append({'bid_time': source_time(row.get('svr_recv_time_bid'), received, clock_evidence, book_zone),
                            'ask_time': source_time(row.get('svr_recv_time_ask'), received, clock_evidence, book_zone),
                            'spread_bps': (ask-bid) / ((ask+bid)/2) * 10000,
                            'execution_status': 'NOT_VERIFIED', 'nbbo_status': 'NOT_VERIFIED'})
    return details


class Evidence:
    def __init__(self, folder, clock, limits=Limits(), clock_evidence=None, evidence_mode='SYNTHETIC_OFFLINE'):
        self.folder, self.clock, self.limits = Path(folder), clock, limits
        self.clock_evidence = clock_evidence
        require(evidence_mode in ('SYNTHETIC_OFFLINE', 'REAL_QUOTE_ENGINEERING_OBSERVATION'), 'EVIDENCE_MODE')
        self.evidence_mode = evidence_mode
        self.count = 0; self.messages = 0; self.head = '0' * 64
        self.seen_ticks = set(); self.seen_books = set()
        self.missing_raw = 0; self.invalid = 0; self.observation_ticks = set(); self.observation_books = set()
        self.duplicate_tickers = 0; self.duplicate_books = 0; self.nonmonotone_tickers = 0
        self.last_ticker_sequence = None
        self.used_bytes = directory_bytes(self.folder)
        self.timings = {}
        self.durable_messages = 0
        self.packed = False

    def write_payload(self, prefix, suffix, data):
        name = prefix+'.'+suffix
        write_once(self.folder/name, data)
        return name, {'sha256': digest(data), 'bytes': len(data)}

    def write_receipt(self, receipt_bytes, receipt):
        with (self.folder/'receipts.jsonl').open('ab') as f:
            f.write(receipt_bytes); f.flush(); os.fsync(f.fileno())
        self.durable_messages = receipt['sequence']

    def finish(self):
        pass

    def close(self):
        pass

    def timed(self, stage, started):
        self.timings.setdefault(stage, []).append((time.perf_counter_ns()-started)/1e6)

    def timing_summary(self):
        return {stage: {'count': len(values), 'total_ms': sum(values),
                       'max_ms': max(values), 'p95_ms': sorted(values)[int((len(values)-1)*.95)]}
                for stage, values in self.timings.items()}

    def accept(self, e, observation=False):
        started = time.perf_counter_ns()
        require(e['epoch'] == 1, 'CONNECTION_EPOCH_CHANGED')
        decoded = json.loads(e['decoded']); native = decoded['native']
        n = len(native) if e['stream'] == 'TICKER' and isinstance(native, list) else 1
        reason = None
        try:
            details = inspect_market(e['stream'], native, e['received'], self.clock_evidence)
        except Stop as exc:
            details, reason = [], str(exc)
        self.timed('decode_quality', started)
        seen_in_batch = set(); previous_sequence = self.last_ticker_sequence
        if reason is None and e['stream'] == 'TICKER':
            for row, detail in zip(native, details):
                key = (e['epoch'], row['code'], str(row['sequence']))
                duplicate = key in self.seen_ticks or key in seen_in_batch
                sequence = row['sequence']
                backwards = isinstance(sequence, int) and previous_sequence is not None and sequence < previous_sequence
                detail.update(duplicate_sequence=duplicate, nonmonotone_sequence=backwards,
                              sequence_gap_interpretation='NOT_PACKET_LOSS_EVIDENCE')
                seen_in_batch.add(key)
                if isinstance(sequence, int):
                    previous_sequence = max(sequence, previous_sequence) if previous_sequence is not None else sequence
        elif reason is None:
            key = digest(encoded({k: native.get(k) for k in ['code', 'order_book_type', 'Bid', 'Ask']}))
            details[0]['duplicate_content'] = key in self.seen_books
        prospective = self.count + n
        estimated = len(e['decoded']) + len(e['raw'] or b'') + len(encoded(details)) + 8192
        # Reserve final manifest space as response-file count grows; 4MiB is a minimum.
        ending_reserve = 4 * 1024 * 1024 + ((self.messages + 1) * 2 + 20) * 192
        used = self.used_bytes
        if (prospective > self.limits.records or used + estimated > self.limits.market_bytes or
                used + estimated + ending_reserve > self.limits.total_bytes):
            if not (self.folder/'UNSTORED_BATCH.json').exists():
                write_once(self.folder/'UNSTORED_BATCH.json', encoded({'reason': 'RESOURCE_LIMIT', 'records': n,
                   'decoded_bytes': len(e['decoded']), 'decoded_sha256': digest(e['decoded']),
                   'raw_bytes': len(e['raw']) if e['raw'] is not None else None,
                   'raw_sha256': digest(e['raw']) if e['raw'] is not None else None}))
            raise Stop('RESOURCE_LIMIT')
        prefix = f'response_{self.messages+1:06d}'
        files = {}
        for suffix, data in [('json', e['decoded']), ('pb', e['raw'])]:
            if data is not None:
                stage_start = time.perf_counter_ns()
                name, info = self.write_payload(prefix, suffix, data)
                self.timed(suffix + '_stage', stage_start)
                files[name] = info
        raw_available = e['raw'] is not None
        receipt = {'sequence': self.messages+1, 'callback_sequence': e['sequence'], 'stream': e['stream'],
                   'epoch': e['epoch'], 'origin': e['origin'], 'received': e['received'],
                   ('staged_at' if self.packed else 'fsync_completed'): self.clock.stamp(), 'files': files, 'previous': self.head,
                   'raw_response_available': raw_available,
                   'raw_status': 'SDK_RESPONSE_SERIALIZED' if raw_available else 'NOT_AVAILABLE',
                   'observation': observation, 'quality': details, 'invalid_reason': reason,
                   'sample_status': 'INVALID' if reason else 'VALID',
                   'mode': self.evidence_mode,
                   'fsync_stamp_scope': ('STAGED_ONLY; durability in commits.jsonl' if self.packed else 'PAYLOAD_FILES; receipt durability measured separately')}
        next_head = digest(encoded(receipt)); receipt['receipt_sha256'] = next_head
        receipt_bytes = encoded(receipt)+b'\n'
        stage_start = time.perf_counter_ns()
        self.write_receipt(receipt_bytes, receipt)
        self.timed('receipt_stage', stage_start)
        self.timed('accept_total', started)
        self.timings.setdefault('receive_to_receipt_staged' if self.packed else 'receive_to_receipt_durable', []).append(
            (self.clock.stamp()['monotonic_ns']-e['received']['monotonic_ns'])/1e6)
        self.head = next_head
        self.messages += 1; self.count = prospective
        self.missing_raw += not raw_available
        self.used_bytes += sum(info['bytes'] for info in files.values()) + len(receipt_bytes)
        if reason:
            self.invalid += 1
            raise QualityError(reason)
        if e['stream'] == 'TICKER':
            self.duplicate_tickers += sum(d['duplicate_sequence'] for d in details)
            self.nonmonotone_tickers += sum(d['nonmonotone_sequence'] for d in details)
            self.last_ticker_sequence = previous_sequence
            for row in native:
                key = (e['epoch'], row['code'], str(row['sequence']))
                self.seen_ticks.add(key)
                if observation: self.observation_ticks.add(key)
        else:
            self.duplicate_books += bool(details[0]['duplicate_content'])
            key = digest(encoded({k: native.get(k) for k in ['code', 'order_book_type', 'Bid', 'Ask']}))
            self.seen_books.add(key)
            if observation: self.observation_books.add(key)
        require(self.count < self.limits.records and self.used_bytes < self.limits.market_bytes,
                'RESOURCE_LIMIT')

    def summary(self, complete):
        return {'messages': self.messages, 'records': self.count, 'unique_tickers': len(self.seen_ticks),
                'book_versions': len(self.seen_books), 'observation_tickers': len(self.observation_ticks),
                'observation_book_versions': len(self.observation_books), 'missing_raw': self.missing_raw,
                'invalid': self.invalid, 'receipt_head': self.head, 'entitlement': 'NOT_VERIFIED',
                'duplicate_tickers': self.duplicate_tickers, 'duplicate_books': self.duplicate_books,
                'nonmonotone_tickers': self.nonmonotone_tickers,
                'source_time': 'NOT_VERIFIED', 'local_clock': 'NOT_VERIFIED',
                'minimum_usable': bool(complete and not self.missing_raw and not self.invalid and
                                       len(self.observation_ticks) >= 100 and len(self.observation_books) >= 20),
                'edge_status': 'NOT_TESTED', 'write_stage_metrics': self.timing_summary()}


class PackedEvidence(Evidence):
    """Same per-envelope bytes/hash/quality; at most 64 staged before durable commit."""
    BATCH = 64

    def __init__(self, folder, clock, limits=Limits(), deadline_check=lambda: None, evidence_mode='SYNTHETIC_OFFLINE'):
        super().__init__(folder, clock, limits, evidence_mode=evidence_mode)
        self.deadline_check = deadline_check
        self.packed = True
        self.last_flush = time.perf_counter()
        self.handles = {}
        self.last_receipt = None
        self.staged = []
        self.commit_failed = False
        for name in ('payload.jsonb', 'payload.pbb', 'receipts.jsonl', 'commits.jsonl'):
            self.handles[name] = (self.folder/name).open('xb', buffering=0)

    def write_payload(self, prefix, suffix, data):
        self.deadline_check()
        name = 'payload.'+('jsonb' if suffix == 'json' else 'pbb')
        f = self.handles[name]
        offset = f.tell()
        require(f.write(data) == len(data), 'SHORT_WRITE')
        return name, {'sha256': digest(data), 'bytes': len(data), 'offset': offset}

    def write_receipt(self, receipt_bytes, receipt):
        self.deadline_check()
        require(self.handles['receipts.jsonl'].write(receipt_bytes) == len(receipt_bytes), 'SHORT_WRITE')
        self.last_receipt = receipt
        self.staged.append(receipt['received']['monotonic_ns'])
        if receipt['sequence']-self.durable_messages >= self.BATCH:
            self.finish()

    def flush_if_due(self):
        if time.perf_counter()-self.last_flush >= .25:
            self.finish()

    def finish(self):
        if not self.staged or self.commit_failed:
            return
        try:
            started = time.perf_counter_ns()
            for name in ('payload.jsonb', 'payload.pbb', 'receipts.jsonl'):
                self.deadline_check()
                t = time.perf_counter_ns()
                self.handles[name].flush(); os.fsync(self.handles[name].fileno())
                self.timed(name+'_flush_fsync', t)
            self.deadline_check()
            checkpoint = {'sequence': self.last_receipt['sequence'],
                'receipt_head': self.last_receipt['receipt_sha256'],
                'payload_and_receipts_fsync_completed': self.clock.stamp(),
                'mode': self.evidence_mode}
            t = time.perf_counter_ns()
            blob = encoded(checkpoint)+b'\n'
            require(self.handles['commits.jsonl'].write(blob) == len(blob), 'SHORT_WRITE')
            self.handles['commits.jsonl'].flush(); os.fsync(self.handles['commits.jsonl'].fileno())
            self.timed('checkpoint_flush_fsync', t)
            self.durable_messages = checkpoint['sequence']
            self.used_bytes += len(blob)
            now = self.clock.stamp()['monotonic_ns']
            self.timings.setdefault('receive_to_commit_durable', []).extend((now-x)/1e6 for x in self.staged)
            self.staged.clear()
            self.last_flush = time.perf_counter()
            self.timed('commit_total', started)
        except BaseException:
            self.commit_failed = True
            raise

    def close(self):
        for f in self.handles.values():
            f.close()


def verify_receipts(folder):
    folder = Path(folder)
    head = '0' * 64; count = 0
    checkpoint_path = folder/'commits.jsonl'
    checkpoint = None
    if checkpoint_path.exists():
        checkpoints = [json.loads(line) for line in checkpoint_path.read_bytes().splitlines()]
        checkpoint = checkpoints[-1] if checkpoints else {'sequence': 0, 'receipt_head': head}
    path = folder/'receipts.jsonl'
    if path.exists():
        with path.open('rb') as receipts:
            for line in receipts:
                if checkpoint is not None and count >= checkpoint['sequence']:
                    break
                row = json.loads(line); expected = row.pop('receipt_sha256')
                require(row['previous'] == head and digest(encoded(row)) == expected, 'RECEIPT_HASH_MISMATCH')
                require(row['sequence'] == count+1, 'RECEIPT_SEQUENCE_MISMATCH')
                require(row.get('fsync_completed', row.get('staged_at'))['monotonic_ns'] >= row['received']['monotonic_ns'], 'RECEIPT_TIME_ORDER')
                for name, info in row['files'].items():
                    require(Path(name).name == name, 'UNSAFE_RECEIPT_PATH')
                    with (folder/name).open('rb') as f:
                        f.seek(info.get('offset', 0)); data = f.read(info['bytes'])
                    require(len(data) == info['bytes'] and digest(data) == info['sha256'], 'RAW_HASH_MISMATCH')
                head = expected; count += 1
    if checkpoint is not None:
        require(count == checkpoint['sequence'] and head == checkpoint['receipt_head'], 'COMMIT_MISMATCH')
    return {'receipt_head': head, 'messages': count}
