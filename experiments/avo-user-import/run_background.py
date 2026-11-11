"""Run the private MV-Centr import with a status file and a completion alert."""
import ctypes
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import msvcrt
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import import_mvcentr_users as migration

STATUS = migration.JOURNAL.with_name('mvcentr-user-import-status.json')
LOG = migration.JOURNAL.with_name('mvcentr-user-import-run.log')
SCRIPT = 'import_mvcentr_users.py'
LABEL = 'пользователей'


def write_status(data):
    data['updated_at'] = datetime.now(timezone.utc).isoformat()
    temp = STATUS.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, STATUS)


def was_stopped(result, code):
    return bool(code != 0 or not result or result.get('stopped') or result.get('stopped_consecutive_issues')
                or result.get('unresolved_write_outcomes') or result.get('readback_mismatch') or result.get('read_error')
                or result.get('create_error',0) > result.get('unique_conflict_skipped',0) + result.get('validation_conflict_skipped',0))


def main():
    report = json.loads((migration.ROOT / 'exports/contacts-api-all-fields/report.json').read_text(encoding='utf-8'))
    if report.get('origin') != 'https://mvcentr.autoweboffice.ru':
        raise RuntimeError('source_account_mismatch')
    state = {'account':'mv-centr','status':'running','created_this_run':0,'worker_pid':os.getpid()}
    write_status(state)
    result = None
    with LOG.open('a', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, '-u', str(HERE/SCRIPT), '--apply', '--limit', '250000'],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for line in process.stdout:
            log.write(line); log.flush()
            try: row=json.loads(line)
            except (ValueError, TypeError): continue
            if 'progress_created' in row:
                state['created_this_run']=row['progress_created'];write_status(state)
            else: result=row
        code=process.wait()
    result = result if isinstance(result,dict) else {}
    state['created_this_run']=result.get('created', result.get('stored', state['created_this_run']))
    stopped = was_stopped(result, code)
    state['status']='stopped' if stopped else 'completed'
    state['result']={k:v for k,v in result.items() if isinstance(k,str) and isinstance(v,int)}
    if isinstance(result.get('stopped'),str):
        state['reason']=result['stopped']
    state['exit_code']=code
    write_status(state)
    message = (f'Перенос {LABEL} МВЦ остановился и требует проверки.' if stopped
               else f'Обработка {LABEL} МВЦ завершена. Проверьте итоговый отчёт.')
    try:
        ctypes.windll.user32.MessageBoxW(0, message, 'Перенос контактов МВЦ', 0x40 | 0x1000)
    except Exception:
        pass


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--no-email',action='store_true')
    mode.add_argument('--priority-list',action='store_true')
    mode.add_argument('--passwords',action='store_true')
    args=parser.parse_args()
    if args.no_email:
        STATUS=STATUS.with_name('mvcentr-noemail-contact-status.json')
        LOG=LOG.with_name('mvcentr-noemail-contact-run.log')
        SCRIPT='import_contacts_no_email.py'
        LABEL='контактов без почты'
    elif args.priority_list:
        STATUS=STATUS.with_name('mvcentr-priority-contact-status.json')
        LOG=LOG.with_name('mvcentr-priority-contact-run.log')
        SCRIPT='import_priority_list.py'
        LABEL='контактов из списка'
    elif args.passwords:
        STATUS=STATUS.with_name('mvcentr-support-password-status.json')
        LOG=LOG.with_name('mvcentr-support-password-run.log')
        SCRIPT='archive_verified_passwords.py'
        LABEL='паролей контактов'
    lock_path = STATUS.with_name('mvcentr-user-import-worker.lock')
    if args.no_email:lock_path=STATUS.with_name('mvcentr-noemail-contact-worker.lock')
    if args.priority_list:lock_path=STATUS.with_name('mvcentr-priority-contact-worker.lock')
    if args.passwords:lock_path=STATUS.with_name('mvcentr-support-password-worker.lock')
    with lock_path.open('a+b') as lock:
        lock.seek(0,2)
        if lock.tell()==0: lock.write(b'0');lock.flush()
        lock.seek(0)
        try: msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError: raise SystemExit('another_worker_is_running')
        try:
            main()
        except Exception:
            write_status({'account':'mv-centr','status':'stopped','reason':'worker_error','worker_pid':os.getpid()})
            try: ctypes.windll.user32.MessageBoxW(0,'Перенос контактов МВЦ остановился и требует проверки.','Перенос контактов МВЦ',0x40|0x1000)
            except Exception: pass
            raise
        finally:
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
