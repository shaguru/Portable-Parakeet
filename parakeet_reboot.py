"""Single-instance supervisor and global restart hotkey for Parakeet Dictation."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
FROZEN = getattr(sys, "frozen", False)
APP = ROOT / ("ParakeetDictation.exe" if FROZEN else "parakeet_dictation.py")
PYTHONW = Path(sys.executable)
APP_PROCESS_NAMES = {"parakeetdictation.exe", "python.exe", "pythonw.exe"}
APP_MARKERS = ("parakeet_dictation.py",)
ERROR_ALREADY_EXISTS = 183
VK_CONTROL = 0x11
VK_ALT = 0x12
VK_SHIFT = 0x10
VK_R = 0x52

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
kernel32.CreateMutexW.restype = ctypes.c_void_p
kernel32.GetLastError.restype = ctypes.c_ulong


def hide_console_kwargs() -> dict:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {"startupinfo": startupinfo, "creationflags": subprocess.CREATE_NO_WINDOW}


def is_app_process(proc: psutil.Process) -> bool:
    try:
        name = (proc.info.get("name") or "").lower()
        if name not in APP_PROCESS_NAMES:
            return False
        command = " ".join(proc.info.get("cmdline") or []).lower()
        if name == "parakeetdictation.exe":
            return True
        return any(marker in command for marker in APP_MARKERS)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False


def stop_app_instances() -> int:
    stopped = 0
    current_pid = os.getpid()
    candidates = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        if proc.pid != current_pid and is_app_process(proc):
            candidates.append(proc)
    for proc in candidates:
        try:
            proc.terminate()
            stopped += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if candidates:
        _, alive = psutil.wait_procs(candidates, timeout=1)
        for proc in alive:
            try:
                proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    return stopped


def start_app() -> None:
    if FROZEN:
        command = [str(APP)]
    else:
        command = [str(PYTHONW), str(APP)]
    subprocess.Popen(command, cwd=str(ROOT), **hide_console_kwargs())


def app_is_running() -> bool:
    """Return whether the one supervised dictation process is alive."""
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        if is_app_process(proc):
            return True
    return False


def start_and_wait() -> bool:
    """Start the app and give Windows a moment to publish its process."""
    try:
        start_app()
    except (OSError, subprocess.SubprocessError):
        return False
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if app_is_running():
            return True
        time.sleep(0.1)
    return app_is_running()


def restart_app() -> None:
    stop_app_instances()
    time.sleep(0.35)
    start_and_wait()


def hotkey_is_down() -> bool:
    return all(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (VK_CONTROL, VK_ALT, VK_SHIFT, VK_R))


def main() -> int:
    mutex = kernel32.CreateMutexW(None, True, "Local\\ParakeetDictation.Supervisor")
    if not mutex or kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return 0
    if not APP.exists():
        return 1
    restart_app()
    previous = False
    # If the app exits during login or crashes later, retry with a short
    # backoff. The named mutex in the app still prevents duplicate launches.
    next_watchdog_start = time.monotonic() + 2.0
    while True:
        current = hotkey_is_down()
        if current and not previous:
            restart_app()
            next_watchdog_start = time.monotonic() + 2.0
        elif not app_is_running() and time.monotonic() >= next_watchdog_start:
            start_and_wait()
            next_watchdog_start = time.monotonic() + 3.0
        previous = current
        time.sleep(0.03)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
