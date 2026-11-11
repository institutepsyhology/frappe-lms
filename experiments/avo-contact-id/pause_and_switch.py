"""Pause the two specified importer children at journal checkpoints around a switch.

Run on Windows with child PIDs and the switch command. A separate watchdog
resumes only the same process instances if the controller is interrupted.
"""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

K = ctypes.WinDLL('kernel32', use_last_error=True)
N = ctypes.WinDLL('ntdll')
K.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
K.OpenProcess.restype = wintypes.HANDLE
K.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
K.CloseHandle.argtypes = [wintypes.HANDLE]
N.NtSuspendProcess.argtypes = [wintypes.HANDLE]
N.NtResumeProcess.argtypes = [wintypes.HANDLE]

def handle(pid):
    h = K.OpenProcess(0x0800 | 0x1000, False, pid)
    if not h: raise OSError('process_unavailable')
    return h

def creation(h):
    a, b, c, d = (wintypes.FILETIME() for _ in range(4))
    if not K.GetProcessTimes(h, ctypes.byref(a), ctypes.byref(b), ctypes.byref(c), ctypes.byref(d)):
        raise OSError('process_identity_unavailable')
    return (a.dwHighDateTime << 32) | a.dwLowDateTime

def watchdog(marker):
    for _ in range(120):
        time.sleep(5)
        if not marker.is_file(): return
    try:
        state = json.loads(marker.read_text(encoding='utf-8'))
        for row in state['processes']:
            try:
                h = handle(row['pid'])
                try:
                    if creation(h) == row['creation']: N.NtResumeProcess(h)
                finally: K.CloseHandle(h)
            except OSError: pass
    finally:
        marker.unlink(missing_ok=True)

def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--watchdog':
        return watchdog(Path(sys.argv[2]))
    if len(sys.argv) < 5 or sys.argv[3] != '--':
        raise SystemExit('usage: pause_and_switch.py recipient_pid password_pid -- switch_command ...')
    recipient, passwords = int(sys.argv[1]), int(sys.argv[2])
    root = Path(__file__).resolve().parents[3] / 'exports/contacts-api-all-fields'
    marker = root / 'contact-id-switch-pause.json'
    handles = []
    suspended = []
    marker_owned = False
    try:
        for pid in (recipient, passwords): handles.append((pid, handle(pid)))
        state = {'processes': [{'pid': pid, 'creation': creation(h)} for pid, h in handles]}
        with marker.open('x', encoding='utf-8') as out: json.dump(state, out)
        marker_owned = True
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--watchdog', str(marker)],
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        events = [(root / 'mvcentr-user-import-events.jsonl', 'created_verified'),
                  (root / 'mvcentr-support-password-events.jsonl', 'stored')]
        for (pid, h), (path, expected) in zip(handles, events):
            with path.open('r', encoding='utf-8') as stream:
                stream.seek(0, 2)
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    line = stream.readline()
                    if not line: time.sleep(0.01); continue
                    try: row = json.loads(line)
                    except ValueError: raise RuntimeError('incomplete_journal_line')
                    if row.get('status') != expected: continue
                    if N.NtSuspendProcess(h) != 0: raise OSError('pause_failed')
                    suspended.append(h)
                    print('worker_paused', flush=True)
                    break
                else: raise TimeoutError('no_safe_checkpoint')
        result = subprocess.run(sys.argv[4:], timeout=600)
        return result.returncode
    finally:
        for h in reversed(suspended): N.NtResumeProcess(h)
        for _, h in handles: K.CloseHandle(h)
        if marker_owned: marker.unlink(missing_ok=True)
        print('workers_resumed', flush=True)

if __name__ == '__main__': raise SystemExit(main() or 0)
