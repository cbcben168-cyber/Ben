"""Small OS-owned lock and bounded process-tree runner for the local updater."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import time


@contextmanager
def task_guard(root, wait=0):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    stream = (root / 'update.guard').open('a+b')
    stream.seek(0, 2)
    if not stream.tell():
        stream.write(b'0'); stream.flush()
    deadline = time.monotonic() + wait
    locked = False
    try:
        while True:
            try:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(.05)
        yield locked
    finally:
        if locked:
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


class ProcessTree:
    """Windows Job Object closes every owned descendant, without PID lookups."""
    def __init__(self, process):
        self.process = process
        self.job = None
        if os.name != 'nt':
            return
        class Basic(ctypes.Structure):
            _fields_ = [('per_process', ctypes.c_int64), ('per_job', ctypes.c_int64),
                        ('flags', wintypes.DWORD), ('min_ws', ctypes.c_size_t),
                        ('max_ws', ctypes.c_size_t), ('active', wintypes.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                        ('scheduling', wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                        ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('process_mem', ctypes.c_size_t),
                        ('job_mem', ctypes.c_size_t), ('peak_process', ctypes.c_size_t),
                        ('peak_job', ctypes.c_size_t)]
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.CreateJobObjectW.restype = wintypes.HANDLE
        api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api = api
        self.job = api.CreateJobObjectW(None, None)
        info = Extended(); info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.job or not api.SetInformationJobObject(self.job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            self.close(); raise ctypes.WinError(ctypes.get_last_error())
        if not api.AssignProcessToJobObject(self.job, wintypes.HANDLE(int(process._handle))):
            self.close(); raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.job:
            self.api.CloseHandle(self.job)
            self.job = None
        elif os.name != 'nt' and self.process.poll() is None:
            import signal
            os.killpg(self.process.pid, signal.SIGKILL)


def bounded_worker(command, timeout, log):
    """Worker waits for stdin until its entire tree belongs to this supervisor."""
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=log, stderr=log,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                               start_new_session=os.name != 'nt')
    tree = None
    try:
        tree = ProcessTree(process)
        process.stdin.write(b'GO\n'); process.stdin.flush(); process.stdin.close()
        return process.wait(timeout=timeout)
    finally:
        if tree:
            tree.close()
        elif process.poll() is None:
            process.kill()
        process.wait(timeout=10)
