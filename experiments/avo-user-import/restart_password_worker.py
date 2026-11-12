"""Replace only the verified password worker at a durable journal checkpoint.

Dry-run is the default. No credentials or command lines are printed. A hidden
watchdog resumes the same child instance if interrupted before termination.
"""
import argparse, ctypes, importlib.util, json, os, subprocess, sys, time
from ctypes import wintypes
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRIVATE = HERE.parents[2] / 'exports/contacts-api-all-fields'
HELPER = HERE.parent / 'avo-contact-id/pause_and_switch.py'
spec = importlib.util.spec_from_file_location('pause_common', HELPER)
common = importlib.util.module_from_spec(spec); spec.loader.exec_module(common)
K, N = common.K, common.N
K.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
K.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
K.LocalFree.argtypes = [wintypes.HANDLE]
shell = ctypes.WinDLL('shell32', use_last_error=True)
shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)


def require(value, message):
    if not value: raise RuntimeError(message)


def script_args(command, script):
    count = ctypes.c_int(); ptr = shell.CommandLineToArgvW(command or '', ctypes.byref(count))
    require(bool(ptr), 'process_command_unavailable')
    try: args = [ptr[i] for i in range(count.value)]
    finally: K.LocalFree(ctypes.cast(ptr, wintypes.HANDLE))
    index = 1
    while index < len(args) and args[index] in ('-u', '-B'): index += 1
    require(index < len(args) and Path(args[index]).resolve() == HERE / script, 'unexpected_worker_script')
    return args[index + 1:]


def verify_details(rows, parent, child):
    by_pid = {int(row['ProcessId']): row for row in rows}
    require(set(by_pid) == {parent, child}, 'worker_process_missing')
    require(int(by_pid[child]['ParentProcessId']) == parent, 'child_parent_changed')
    require(all(Path(row.get('ExecutablePath') or '').resolve() == Path(sys.executable).resolve()
                for row in rows), 'unexpected_worker_executable')
    require('--passwords' in script_args(by_pid[parent].get('CommandLine'), 'run_background.py'), 'unexpected_worker_mode')
    require('--apply' in script_args(by_pid[child].get('CommandLine'), 'archive_verified_passwords.py'), 'password_worker_not_applying')


def details(parent, child):
    command = ('[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-CimInstance Win32_Process -Filter '
        f'"ProcessId = {parent} OR ProcessId = {child}" | '
        'Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress')
    raw = subprocess.check_output(['powershell', '-NoProfile', '-NonInteractive', '-Command', command],
        encoding='utf-8-sig', stderr=subprocess.DEVNULL, timeout=20)
    rows = json.loads(raw); rows = rows if isinstance(rows, list) else [rows]
    verify_details(rows, parent, child)


def selection(path):
    path = path.resolve(strict=True)
    require(path.is_relative_to(PRIVATE.resolve()), 'selection_outside_private_workspace')
    ids = json.loads(path.read_text(encoding='utf-8-sig'))
    require(isinstance(ids, list) and ids and all(type(i) is int and i > 0 for i in ids)
            and len(ids) == len(set(ids)), 'invalid_selection')
    return path, len(ids)


def stop(handle):
    if K.WaitForSingleObject(handle, 0) == 258:
        require(K.TerminateProcess(handle, 1), 'worker_stop_failed')
    require(K.WaitForSingleObject(handle, 10000) == 0, 'worker_did_not_exit')


def start(path):
    with (PRIVATE / 'mvcentr-support-password-restart.log').open('ab') as log:
        return subprocess.Popen([sys.executable, str(HERE / 'run_background.py'), '--passwords',
            '--password-ids-file', str(path)], cwd=str(HERE.parents[1]), stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-pid', type=int, required=True)
    parser.add_argument('--child-pid', type=int, required=True)
    parser.add_argument('--ids-file', type=Path, required=True)
    parser.add_argument('--apply', action='store_true'); args = parser.parse_args()
    parent, child = args.parent_pid, args.child_pid
    require(parent > 0 and child > 0 and parent != child and os.getpid() not in (parent, child), 'invalid_process_ids')
    path, count = selection(args.ids_file)
    require('--password-ids-file' in (HERE / 'run_background.py').read_text(encoding='utf-8-sig'), 'new_worker_cli_not_ready')
    handles = []; marker = PRIVATE / 'password-worker-restart-pause.json'
    suspended = cutover = owned = False; replacement = None
    try:
        for pid in (parent, child):
            h = K.OpenProcess(0x0001 | 0x0800 | 0x1000 | 0x100000, False, pid)
            require(bool(h), 'worker_handle_unavailable'); handles.append(h)
        identities = [common.creation(h) for h in handles]
        details(parent, child)
        require(all(K.WaitForSingleObject(h, 0) == 258 for h in handles)
                and identities[0] <= identities[1], 'worker_instance_changed')
        state = json.loads((PRIVATE / 'mvcentr-support-password-status.json').read_text(encoding='utf-8-sig'))
        require(state.get('account') == 'mv-centr' and state.get('worker_pid') == parent
                and state.get('status') == 'running', 'password_status_changed')
        if not args.apply:
            print(json.dumps({'verified': True, 'parent_pid': parent, 'child_pid': child,
                'creation_ids': identities, 'selected_count': count, 'dry_run': True})); return
        with marker.open('x', encoding='utf-8') as out:
            json.dump({'processes': [{'pid': child, 'creation': identities[1]}]}, out)
        owned = True
        subprocess.Popen([sys.executable, str(HELPER), '--watchdog', str(marker)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        with (PRIVATE / 'mvcentr-support-password-events.jsonl').open(encoding='utf-8') as stream:
            stream.seek(0, 2); deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                position = stream.tell()
                line = stream.readline()
                if not line: time.sleep(.01); continue
                if not line.endswith('\n'):
                    stream.seek(position); time.sleep(.01); continue
                row = json.loads(line)
                if row.get('account') != 'mv-centr' or row.get('status') != 'stored': continue
                require(N.NtSuspendProcess(handles[1]) == 0, 'worker_pause_failed'); suspended = True; break
            else: raise TimeoutError('no_safe_password_checkpoint')
        details(parent, child)
        require([common.creation(h) for h in handles] == identities, 'worker_instance_changed')
        stop(handles[0]); cutover = True
        stop(handles[1]); replacement = start(path)
        print(json.dumps({'restarted_parent_pid': replacement.pid, 'selected_count': count}))
    finally:
        try:
            if cutover and replacement is None:
                stop(handles[1]); replacement = start(path)
                print(json.dumps({'recovery_parent_pid': replacement.pid, 'selected_count': count}))
        finally:
            resume_failed = False
            if suspended and K.WaitForSingleObject(handles[1], 0) == 258:
                resume_failed = N.NtResumeProcess(handles[1]) != 0
            for h in handles: K.CloseHandle(h)
            if owned and not resume_failed: marker.unlink(missing_ok=True)


if __name__ == '__main__': main()
