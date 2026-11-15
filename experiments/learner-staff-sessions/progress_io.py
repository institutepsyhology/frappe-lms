"""Atomic local status files with bounded retries for Windows reader locks."""
import json
import errno
import os
from pathlib import Path
import time


class ProgressWriteError(OSError):
    """A status-file lock survived bounded retries; contains no source values."""


def _sharing_error(error):
    return os.name == 'nt' and (
        getattr(error, 'winerror', None) in (5, 32, 33)
        or isinstance(error, PermissionError) and error.errno in (errno.EACCES, errno.EPERM))


def write_json(path, value, *, temporary=None, attempts=12, pause=time.sleep):
    path = Path(path)
    temporary = Path(temporary) if temporary is not None else path.with_name(path.name + '.tmp')
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True).encode('utf-8')
    try:
        for attempt in range(attempts):
            try:
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(descriptor, 'wb') as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
                return
            except OSError as error:
                if not _sharing_error(error):
                    raise
                if attempt + 1 == attempts:
                    wrapped = ProgressWriteError(error.errno or 13, 'progress_file_locked')
                    wrapped.winerror = getattr(error, 'winerror', None)
                    raise wrapped from None
                pause(min(0.02 * 2**attempt, 0.25))
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError as error:
            if not _sharing_error(error):
                raise


def read_json(path, *, max_bytes=65536, attempts=8, pause=time.sleep):
    path = Path(path)
    for attempt in range(attempts):
        try:
            with path.open('rb') as stream:
                raw = stream.read(max_bytes + 1)
            break
        except OSError as error:
            if not _sharing_error(error) or attempt + 1 == attempts:
                raise
            pause(min(0.005 * 2**attempt, 0.04))
    if len(raw) > max_bytes:
        raise ValueError('progress_too_large')
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError('invalid_progress')
    return result
