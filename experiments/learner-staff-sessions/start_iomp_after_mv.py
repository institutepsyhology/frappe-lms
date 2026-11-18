"""Run the IOMP contact import as the next stage after the selected MV import."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys


SITES = Path('/home/frappe/frappe-bench/sites')
MV = 'my-lk.mastervision.su'
IOMP = 'my-lk.iomp.ru'
SUCCESS_COUNTS = {'created_user', 'created_contact', 'existing_preserved', 'existing_optout_set'}
ACTIVE_STATES = {'applying', 'waiting_for_queue', 'waiting_for_space'}


class HandoffError(Exception):
    pass


def report(status, **details):
    print(json.dumps({'at': datetime.now(timezone.utc).isoformat(), 'status': status, **details}), flush=True)


@contextmanager
def worker_lock(path, *, create=False, wait=False):
    import fcntl

    flags = (os.O_WRONLY | os.O_CREAT if create else os.O_RDONLY) | os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def checked_receipt(row, selection, expected_count):
    if (row.get('account'), row.get('site'), row.get('selection_fingerprint'), row.get('selection_count')) != (
        'mastervision', MV, selection, expected_count,
    ):
        raise HandoffError('mv_selection_mismatch')
    return row


def require_completed(row, selection, expected_count):
    checked_receipt(row, selection, expected_count)
    counts = row.get('counts')
    if (row.get('status') != 'completed' or not isinstance(counts, dict) or set(counts) - SUCCESS_COUNTS
            or any(type(n) is not int or n < 0 for n in counts.values()) or sum(counts.values()) != expected_count):
        raise HandoffError('mv_completion_not_verified')


def stop_identity(path):
    record = path.lstat()
    if not stat.S_ISREG(record.st_mode) or record.st_uid != os.getuid() or record.st_nlink != 1:
        raise HandoffError('unexpected_iomp_pause_file')
    return record.st_dev, record.st_ino, record.st_mtime_ns, record.st_size


def start_iomp(base, release, original_pause):
    pause = base / 'STOP'
    saved_pause = base / 'STOP.before-mv-handoff'
    if stop_identity(pause) != original_pause or saved_pause.exists():
        raise HandoffError('iomp_pause_changed')
    pause.rename(saved_pause)
    try:
        worker = base / ('release-' + release) / 'apply_server_contacts.py'
        result = subprocess.run(
            [sys.executable, '-B', str(worker), '--account', 'iomp', '--start'],
            cwd=SITES, capture_output=True, timeout=45, check=True,
        )
        started = json.loads(result.stdout)
        if (started.get('status'), started.get('account'), started.get('site')) != ('starting', 'iomp', IOMP):
            raise HandoffError('iomp_start_not_confirmed')
        return started['worker_pid']
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, HandoffError):
        if not pause.exists():
            saved_pause.rename(pause)
        raise HandoffError('iomp_start_not_confirmed') from None


def run(selection, expected_count, release):
    if (not re.fullmatch('[a-f0-9]{64}', selection) or not re.fullmatch('[a-f0-9]{40}', release)
            or expected_count < 1):
        raise HandoffError('invalid_handoff_arguments')
    mv = SITES / MV / 'private'
    receipt = mv / 'selected-contacts' / selection / 'application' / 'progress.json'
    iomp = SITES / IOMP / 'private' / 'apply-avo-contacts'
    if not (iomp / ('release-' + release) / 'apply_server_contacts.py').is_file():
        raise HandoffError('missing_iomp_release')
    with worker_lock(iomp / 'after-mv.lock', create=True):
        original_pause = stop_identity(iomp / 'STOP')
        progress = checked_receipt(json.loads(receipt.read_text()), selection, expected_count)
        if progress.get('status') not in ACTIVE_STATES:
            require_completed(progress, selection, expected_count)
        report('queued', mv_records=expected_count, target=IOMP)
        # The native MV writer owns this lock for its entire run, including final verification.
        with worker_lock(mv / 'apply-avo-contacts' / 'worker.lock', wait=True):
            require_completed(json.loads(receipt.read_text()), selection, expected_count)
            pid = start_iomp(iomp, release, original_pause)
        report('iomp_started', worker_pid=pid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection', required=True)
    parser.add_argument('--expected-count', required=True, type=int)
    parser.add_argument('--release', required=True)
    args = parser.parse_args()
    try:
        run(args.selection, args.expected_count, args.release)
    except HandoffError as exc:
        report('blocked', reason=str(exc))
        return 1
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        report('blocked', reason=type(exc).__name__)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
