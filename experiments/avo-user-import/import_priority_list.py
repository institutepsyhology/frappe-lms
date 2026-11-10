"""Import the selected MV-Centr IDs while the general importer remains paused.

The general worker must be restarted from its journal, not resumed from its
old in-memory position, after this job has finished.
"""
import json
import msvcrt
from pathlib import Path
import sys

import import_mvcentr_users as source

PRIVATE = source.JOURNAL.parent
SELECTION = PRIVATE / 'mvcentr-nov10-priority-ready-ids.json'


def main():
    paused = json.loads((PRIVATE / 'mvcentr-user-import-status.json').read_text(encoding='utf-8-sig'))
    marker = json.loads((PRIVATE / 'mvcentr-user-import-paused.json').read_text(encoding='utf-8-sig'))
    if paused.get('status') != 'paused' or marker.get('status') != 'paused' or paused.get('worker_pid') != marker.get('worker_pid'):
        raise RuntimeError('general_import_not_paused')
    if not SELECTION.is_file():
        raise RuntimeError('selection_missing')
    lock_path = PRIVATE / 'mvcentr-priority-contact-import.lock'
    with lock_path.open('a+b') as lock:
        lock.seek(0, 2)
        if lock.tell() == 0:
            lock.write(b'0'); lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError('priority_import_already_running') from exc
        try:
            sys.argv.extend(['--ids-file', str(SELECTION)])
            source.main()
        finally:
            lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == '__main__':
    main()
