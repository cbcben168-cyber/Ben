"""Single worker with bounded callbacks; the independent supervisor enforces blocking calls."""
from __future__ import annotations

import json
from pathlib import Path
import queue
import socket
import time

from core import (Clock, Evidence, PackedEvidence, Guard, Inbox, SLOTS, Stop, QualityError, QualityPolicy, control, encoded,
                  require, utc, write_once, verify_receipts)


class Calls:
    def __init__(self, folder, clock, guard):
        self.folder, self.clock, self.guard = Path(folder), clock, guard
        self.used = []; self.records = []

    def invoke(self, slot, fn, cleanup=False):
        if slot == 'close':
            # Close must run even if clock/control fsync has failed. The Job watchdog
            # bounds a blocked close; this still consumes exactly its ninth slot.
            require(slot not in self.used and len(self.used) < 9, 'SDK_BUDGET')
            self.used.append(slot)
            try:
                control(self.folder, {'slot': slot, 'started': self.clock.stamp(), 'in_call': True})
            except (OSError, Stop):
                pass
            result = fn()
            require(result[0] == 0, 'CLEANUP_REJECTED')
            control(self.folder, {'slot': slot, 'in_call': False, 'completed': self.clock.stamp(), 'calls_used': self.used})
            return result[1]
        stamp = self.guard.check()
        if slot in ('connect', 'state', 'subscription_before', 'subscribe', 'subscription_after'):
            require(utc(stamp['utc']) < utc(self.guard.window['start']), 'PREFLIGHT_LATE')
        require(slot in SLOTS and slot not in self.used and len(self.used) < 9, 'SDK_BUDGET')
        self.used.append(slot)
        start = self.clock.stamp()
        control(self.folder, {'slot': slot, 'started': start, 'in_call': True})
        result = None
        try:
            result = fn()
            end = self.clock.stamp()
            require((end['monotonic_ns']-start['monotonic_ns'])/1e9 <= 5, 'SDK_TIMEOUT')
            ret, data = result
            require(isinstance(ret, int), 'SDK_RETURN_SHAPE')
            # Only the adapter's management white lists enter data evidence.
            record = {'slot': slot, 'start': start, 'end': end, 'ret': ret,
                      'error': None if ret == 0 else 'SDK_REJECTED'}
            if slot in ('state', 'subscription_before', 'subscription_after') and ret == 0:
                record['data'] = data
            self.records.append(record)
            write_once(self.folder/f'call_{len(self.used):02d}.json', encoded(record))
            if not cleanup:
                require(ret == 0, 'PERMISSION_OR_SDK_REJECTED')
            else:
                require(ret == 0, 'CLEANUP_REJECTED')
            return data
        except Stop:
            raise
        except Exception:
            raise Stop('SDK_EXCEPTION') from None
        finally:
            control(self.folder, {'slot': slot, 'in_call': False,
                   'completed': self.clock.stamp(), 'calls_used': self.used})


def tcp_once():
    try:
        with socket.create_connection(('127.0.0.1', 11111), timeout=1):
            pass
    except OSError:
        raise Stop('TCP_UNAVAILABLE') from None


def collect(folder, config, clock=None, factory=None, tcp=tcp_once, limits=None):
    # This candidate accepts offline injection only. No live authorization/entry is copied.
    from core import Limits, directory_bytes
    require(factory is not None and tcp is not tcp_once, 'OFFLINE_INJECTION_REQUIRED')
    return _collect(folder, config, clock, factory, tcp, limits, 'SYNTHETIC_OFFLINE')


def collect_live(folder, config):
    """Production path: fixed SDK adapter, real clock/TCP, no injection seam."""
    from live_entry import validate_worker
    validate_worker(folder, config)
    return _collect(folder, config, None, None, tcp_once, None, 'REAL_QUOTE_ENGINEERING_OBSERVATION')


def _collect(folder, config, clock, factory, tcp, limits, evidence_mode):
    from core import Limits, directory_bytes
    clock = clock or Clock(); limits = limits or Limits()
    folder = Path(folder); guard = Guard(clock, config['window'])
    policy = QualityPolicy()
    inbox = Inbox(clock, limits); evidence = PackedEvidence(folder, clock, limits, guard.check, evidence_mode)
    calls = Calls(folder, clock, guard); adapter = None; subscribed_at = None
    complete = False; reason = 'NOT_STARTED'; cleanup_errors = []
    first = {}; pulled = set(); observing_at = None
    last_loop = None; maximum_loop_gap = 0
    cleanup_quality_errors = []
    fatal = None
    def save_envelope(e, cleanup=False):
        in_window = utc(config['window']['start']) <= utc(e['received']['utc']) < utc(config['window']['end'])
        quality_reason = None
        try:
            evidence.accept(e, observation=in_window)
        except QualityError as exc:
            quality_reason = str(exc)
            if cleanup:
                cleanup_quality_errors.append({'callback_sequence': e['sequence'], 'reason': quality_reason})
        if not cleanup:
            policy.observe(e['stream'], in_window, quality_reason)
        return in_window

    try:
        guard.launch()
        require((folder/'INVOCATION_ONCE.json').exists(), 'MISSING_INVOCATION')
        tcp()
        guard.check()
        if evidence_mode == 'REAL_QUOTE_ENGINEERING_OBSERVATION':
            from sdk_adapter import Adapter
            adapter = Adapter(inbox)
        else:
            adapter = factory(inbox)
        calls.invoke('connect', adapter.connect)
        state = calls.invoke('state', adapter.state)
        require(state.get('qot_logined') is True, 'QUOTE_NOT_LOGGED_IN')
        if config.get('expected_opend_version'):
            require(state.get('server_ver') == config['expected_opend_version'], 'OPEND_VERSION_CHANGED')
        subscription = calls.invoke('subscription_before', adapter.subscription)
        from runtime_isolation import known_quota_insufficient
        require(not known_quota_insufficient(subscription), 'KNOWN_QUOTA_INSUFFICIENT')
        calls.invoke('subscribe', adapter.subscribe)
        subscribed_at = clock.stamp()['monotonic_ns']
        calls.invoke('subscription_after', adapter.subscription)
        require(utc(clock.stamp()['utc']) < utc(config['window']['start']), 'PREFLIGHT_LATE')
        while True:
            stamp = guard.check()
            if last_loop is not None:
                gap = (stamp['monotonic_ns']-last_loop)/1e9
                maximum_loop_gap = max(maximum_loop_gap, gap)
                if evidence_mode == 'REAL_QUOTE_ENGINEERING_OBSERVATION':
                    require(gap <= 1, 'OBSERVATION_CONTINUITY_NOT_PROVEN')
            last_loop = stamp['monotonic_ns']
            require(inbox.fault is None, inbox.fault or 'INBOX_FAILED')
            if utc(stamp['utc']) >= utc(config['window']['end']):
                complete = True; reason = 'WINDOW_COMPLETE'; break
            observing = utc(stamp['utc']) >= utc(config['window']['start'])
            if observing and observing_at is None:
                observing_at = stamp['monotonic_ns']
            if observing:
                require((stamp['monotonic_ns']-observing_at)/1e9 < 300, 'OBSERVATION_DURATION_LIMIT')
            try:
                e = inbox.q.get_nowait()
            except queue.Empty:
                e = None
            if e:
                in_window = save_envelope(e)
                if in_window and e['origin'] == 'push': first[e['stream']] = True
            for stream, slot in [('TICKER', 'ticker_pull'), ('ORDER_BOOK', 'book_pull')]:
                if observing and stream not in pulled and (first.get(stream) or
                        (utc(stamp['utc'])-utc(config['window']['start'])).total_seconds() >= 5):
                    pulled.add(stream)
                    calls.invoke(slot, lambda stream=stream: adapter.pull(stream))
            if e is None:
                evidence.flush_if_due()
                clock.sleep(.01)
    except Stop as exc:
        reason = str(exc); fatal = reason
    except OSError:
        reason = fatal = 'WRITE_FAILED'
    except Exception as exc:
        reason = fatal = 'WORKER_EXCEPTION_' + type(exc).__name__
    finally:
        inbox.close_reception()
        cleanup_started = time.perf_counter()
        cleanup_initial = clock.stamp()['monotonic_ns']
        def cleanup_check():
            guard.check()
            require(time.perf_counter()-cleanup_started < 10 and
                    (clock.stamp()['monotonic_ns']-cleanup_initial)/1e9 < 10, 'CLEANUP_DEADLINE')
        evidence.deadline_check = cleanup_check
        # Only I/O/resource/deadline faults stop saving, quality faults are per envelope.
        unsafe_to_save = reason in ('RESOURCE_LIMIT', 'WRITE_FAILED', 'SHORT_WRITE', 'HARD_DEADLINE', 'CLOCK_JUMP')
        while not inbox.q.empty() and not unsafe_to_save:
            try:
                cleanup_check()
                save_envelope(inbox.q.get_nowait(), cleanup=True)
            except (Stop, OSError) as exc:
                complete = False
                code = str(exc) if isinstance(exc, Stop) else 'WRITE_FAILED'
                cleanup_errors.append(code)
                break
        try:
            if (reason not in ('WRITE_FAILED', 'SHORT_WRITE') and
                    not any(x in ('WRITE_FAILED', 'SHORT_WRITE') for x in cleanup_errors) and
                    not evidence.commit_failed):
                evidence.finish()
        except (Stop, OSError) as exc:
            complete = False
            cleanup_errors.append(str(exc) if isinstance(exc, Stop) else 'WRITE_FAILED')
        evidence.close()
        cleanup_ms = (time.perf_counter()-cleanup_started)*1000
        if adapter is not None:
            if subscribed_at is not None and (clock.stamp()['monotonic_ns']-subscribed_at)/1e9 >= 60:
                try:
                    cleanup_check()
                    calls.invoke('unsubscribe', adapter.unsubscribe, cleanup=True)
                except (Stop, OSError) as exc:
                    cleanup_errors.append('UNSUBSCRIBE_' + (str(exc) if isinstance(exc, Stop) else 'WRITE_FAILED'))
            try:
                calls.invoke('close', adapter.close, cleanup=True)
            except Exception as exc:
                cleanup_errors.append('CLOSE_' + (str(exc) if isinstance(exc, Stop) else 'CLOSE_NOT_VERIFIED'))
        try:
            cleanup_check()
            if inbox.unstored:
                write_once(folder/'UNSTORED_CALLBACK.json', encoded(inbox.unstored))
            if inbox.fault:
                complete = False
                fatal = fatal or inbox.fault
            checked = verify_receipts(folder)
            require(checked['messages'] == evidence.durable_messages, 'FINAL_CHAIN_MISMATCH')
            unsaved = inbox.accepted - evidence.durable_messages
            accounting = {'received': inbox.received, 'accepted': inbox.accepted,
                'saved': evidence.durable_messages, 'unsaved_accepted': unsaved, 'rejected': inbox.rejected,
                'after_close': inbox.after_close, 'queue_peak': inbox.peak,
                'pending': inbox.q.qsize(), 'dequeued_unsaved': unsaved-inbox.q.qsize()}
            require(inbox.received == inbox.accepted+inbox.rejected+inbox.after_close and
                    unsaved >= inbox.q.qsize(), 'COUNT_MISMATCH')
            require(directory_bytes(folder) < limits.total_bytes, 'RESOURCE_LIMIT')
            clean = (complete and not cleanup_errors and not unsaved and not inbox.rejected and
                     not evidence.invalid and not evidence.missing_raw)
            summary = evidence.summary(clean)
            summary['processed_messages'] = evidence.messages
            summary['processed_receipt_head'] = summary['receipt_head']
            summary['receipt_head'] = checked['receipt_head']
            summary['messages'] = evidence.durable_messages
            summary['quality_count_scope'] = 'PROCESSED; only messages/accounting.saved and receipt_head are durable'
            from runtime_isolation import STATUS_FIELDS
            resource = {k: config.get('resource_isolation', {}).get(k) for k in STATUS_FIELDS}
            if reason == 'KNOWN_QUOTA_INSUFFICIENT': resource['known_conflict'] = True
            resource['proceed_allowed'] = False  # offline engineering never authorizes a live run
            summary['resource_check'] = resource
            summary.update(reason=reason, status='COMPLETE' if clean else 'PARTIAL',
                           window_complete=complete, first_fatal=fatal, accounting=accounting,
                           cleanup_quality_errors=cleanup_quality_errors, cleanup_ms=cleanup_ms,
                           policy_counts=policy.crossed,
                           maximum_loop_gap_seconds=maximum_loop_gap,
                           calls_used=calls.used, cleanup_errors=cleanup_errors, pending=inbox.q.qsize(),
                           inbox_fault=inbox.fault, mode='SYNTHETIC' if evidence_mode == 'SYNTHETIC_OFFLINE' else evidence_mode)
            summary['cleanup_total_ms'] = (time.perf_counter()-cleanup_started)*1000
            cleanup_check()
            write_once(folder/'COLLECTION_SUMMARY.json', encoded(summary))
        except Exception:
            # Supervisor will retain partial bytes and report persistence failure.
            summary = {'reason': 'PERSISTENCE_NOT_VERIFIED', 'status': 'PARTIAL',
                       'first_fatal': fatal, 'cleanup_errors': cleanup_errors,
                       'accepted': inbox.accepted, 'saved': evidence.durable_messages,
                       'unsaved_accepted': inbox.accepted-evidence.durable_messages, 'pending': inbox.q.qsize(),
                       'accounting': {'received': inbox.received, 'accepted': inbox.accepted,
                           'saved': evidence.durable_messages, 'rejected': inbox.rejected,
                           'after_close': inbox.after_close, 'queue_peak': inbox.peak,
                           'unsaved_accepted': inbox.accepted-evidence.durable_messages,
                           'pending': inbox.q.qsize(),
                           'dequeued_unsaved': inbox.accepted-evidence.durable_messages-inbox.q.qsize()},
                       'cleanup_total_ms': (time.perf_counter()-cleanup_started)*1000}
    return summary
