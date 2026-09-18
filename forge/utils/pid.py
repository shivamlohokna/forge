"""Cross-platform process liveness checks for Forge."""

from __future__ import annotations

import os
import sys


def is_process_alive(pid: int) -> bool:
    """Return True when PID belongs to a process that is alive."""
    if pid <= 0:
        return False

    if sys.platform == "win32":
        return _is_process_alive_windows(pid)

    return _is_process_alive_posix(pid)


def _is_process_alive_posix(pid: int) -> bool:
    """Check process existence on POSIX systems."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True

    return True


def _is_process_alive_windows(pid: int) -> bool:
    """Check process existence using the Windows API."""
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    ERROR_INVALID_PARAMETER = 87
    ERROR_FILE_NOT_FOUND = 2
    ERROR_ACCESS_DENIED = 5

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    kernel32.OpenProcess.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    kernel32.OpenProcess.restype = wintypes.HANDLE

    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION,
        False,
        pid,
    )

    if handle:
        kernel32.CloseHandle(handle)
        return True

    error = ctypes.get_last_error()

    if error in (ERROR_INVALID_PARAMETER, ERROR_FILE_NOT_FOUND):
        return False

    if error == ERROR_ACCESS_DENIED:
        return True

    return True