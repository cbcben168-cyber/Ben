"""Windows Job created before child resumes; never touches other processes."""
import ctypes as ct
from ctypes import wintypes as wt
import subprocess
import time

from core import require


def in_job():
    k = ct.WinDLL('kernel32', use_last_error=True)
    k.GetCurrentProcess.restype = wt.HANDLE
    k.IsProcessInJob.argtypes = [wt.HANDLE, wt.HANDLE, ct.POINTER(wt.BOOL)]
    k.IsProcessInJob.restype = wt.BOOL
    result = wt.BOOL()
    require(k.IsProcessInJob(k.GetCurrentProcess(), None, ct.byref(result)), 'JOB_QUERY_FAILED')
    return bool(result.value)


class IO(ct.Structure):
    _fields_ = [(n, ct.c_ulonglong) for n in ('ReadOperationCount', 'WriteOperationCount',
        'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class Basic(ct.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ct.c_longlong), ('PerJobUserTimeLimit', ct.c_longlong),
        ('LimitFlags', wt.DWORD), ('MinimumWorkingSetSize', ct.c_size_t),
        ('MaximumWorkingSetSize', ct.c_size_t), ('ActiveProcessLimit', wt.DWORD),
        ('Affinity', ct.c_size_t), ('PriorityClass', wt.DWORD), ('SchedulingClass', wt.DWORD)]


class Extended(ct.Structure):
    _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', IO)] + [(n, ct.c_size_t) for n in
        ('ProcessMemoryLimit', 'JobMemoryLimit', 'PeakProcessMemoryUsed', 'PeakJobMemoryUsed')]


class Startup(ct.Structure):
    _fields_ = [('cb', wt.DWORD), ('lpReserved', wt.LPWSTR), ('lpDesktop', wt.LPWSTR),
        ('lpTitle', wt.LPWSTR)] + [(n, wt.DWORD) for n in ('dwX', 'dwY', 'dwXSize', 'dwYSize',
        'dwXCountChars', 'dwYCountChars', 'dwFillAttribute', 'dwFlags')] + [
        ('wShowWindow', wt.WORD), ('cbReserved2', wt.WORD), ('lpReserved2', ct.POINTER(wt.BYTE)),
        ('hStdInput', wt.HANDLE), ('hStdOutput', wt.HANDLE), ('hStdError', wt.HANDLE)]


class ProcessInfo(ct.Structure):
    _fields_ = [('hProcess', wt.HANDLE), ('hThread', wt.HANDLE),
                ('dwProcessId', wt.DWORD), ('dwThreadId', wt.DWORD)]


class Accounting(ct.Structure):
    _fields_ = [(n, ct.c_longlong) for n in ('TotalUserTime', 'TotalKernelTime',
        'ThisPeriodTotalUserTime', 'ThisPeriodTotalKernelTime')] + [(n, wt.DWORD) for n in
        ('TotalPageFaultCount', 'TotalProcesses', 'ActiveProcesses', 'TotalTerminatedProcesses')]


class Job:
    def __init__(self, argv, cwd):
        self.k = ct.WinDLL('kernel32', use_last_error=True)
        signatures = {
            'CreateJobObjectW': ([ct.c_void_p, wt.LPCWSTR], wt.HANDLE),
            'SetInformationJobObject': ([wt.HANDLE, ct.c_int, ct.c_void_p, wt.DWORD], wt.BOOL),
            'CreateProcessW': ([wt.LPCWSTR, wt.LPWSTR, ct.c_void_p, ct.c_void_p, wt.BOOL,
                wt.DWORD, ct.c_void_p, wt.LPCWSTR, ct.POINTER(Startup), ct.POINTER(ProcessInfo)], wt.BOOL),
            'AssignProcessToJobObject': ([wt.HANDLE, wt.HANDLE], wt.BOOL),
            'ResumeThread': ([wt.HANDLE], wt.DWORD), 'CloseHandle': ([wt.HANDLE], wt.BOOL),
            'TerminateJobObject': ([wt.HANDLE, wt.UINT], wt.BOOL),
            'TerminateProcess': ([wt.HANDLE, wt.UINT], wt.BOOL),
            'WaitForSingleObject': ([wt.HANDLE, wt.DWORD], wt.DWORD),
            'GetExitCodeProcess': ([wt.HANDLE, ct.POINTER(wt.DWORD)], wt.BOOL)}
        signatures['QueryInformationJobObject'] = ([wt.HANDLE, ct.c_int, ct.c_void_p,
            wt.DWORD, ct.c_void_p], wt.BOOL)
        for name, (args, result) in signatures.items():
            fn = getattr(self.k, name); fn.argtypes = args; fn.restype = result
        self.job = self.process = None
        self._stop_deadline = None
        try:
            self.job = self.k.CreateJobObjectW(None, None)
            require(bool(self.job), 'CREATE_JOB_FAILED')
            limits = Extended(); limits.BasicLimitInformation.LimitFlags = 0x2000
            require(self.k.SetInformationJobObject(self.job, 9, ct.byref(limits), ct.sizeof(limits)), 'JOB_LIMIT_FAILED')
            startup = Startup(); startup.cb = ct.sizeof(startup); info = ProcessInfo()
            command = ct.create_unicode_buffer(subprocess.list2cmdline(argv))
            require(self.k.CreateProcessW(argv[0], command, None, None, False, 0x00000004 | 0x08000000,
                None, str(cwd), ct.byref(startup), ct.byref(info)), 'CREATE_SUSPENDED_FAILED')
            self.process, self.pid = info.hProcess, info.dwProcessId
            try:
                require(self.k.AssignProcessToJobObject(self.job, self.process), 'ASSIGN_JOB_FAILED')
                require(self.k.ResumeThread(info.hThread) != 0xffffffff, 'RESUME_FAILED')
            except BaseException:
                self.k.TerminateProcess(self.process, 2)
                raise
            finally:
                self.k.CloseHandle(info.hThread)
        except BaseException:
            self.close(); raise

    def wait(self, milliseconds=0):
        result = self.k.WaitForSingleObject(self.process, milliseconds)
        require(result in (0, 258), 'PROCESS_WAIT_FAILED')
        # A root process handle can signal while its descendants are still alive.
        return result == 0 and self.active_processes() == 0

    def active_processes(self):
        accounting = Accounting()
        require(self.k.QueryInformationJobObject(self.job, 1, ct.byref(accounting),
            ct.sizeof(accounting), None), 'JOB_ACCOUNTING_FAILED')
        return accounting.ActiveProcesses

    def stop(self):
        # The supervisor requests shutdown at 4.7s: retain headroom inside 5s.
        # Repeated cleanup shares this deadline; it never resets or reissues kill.
        if self._stop_deadline is None:
            self._stop_deadline = time.monotonic() + .2
            require(self.k.TerminateJobObject(self.job, 2), 'TERMINATE_JOB_FAILED')
        while True:
            require(time.monotonic() < self._stop_deadline, 'TERMINATION_NOT_CONFIRMED')
            if self.wait(0):
                require(time.monotonic() < self._stop_deadline, 'TERMINATION_NOT_CONFIRMED')
                return
            remaining = self._stop_deadline - time.monotonic()
            require(remaining > 0, 'TERMINATION_NOT_CONFIRMED')
            time.sleep(min(.005, remaining))

    def exitcode(self):
        result = wt.DWORD()
        require(self.k.GetExitCodeProcess(self.process, ct.byref(result)), 'EXITCODE_UNAVAILABLE')
        return result.value

    def close(self):
        if self.job:
            self.k.CloseHandle(self.job); self.job = None
        if self.process:
            self.k.CloseHandle(self.process); self.process = None
