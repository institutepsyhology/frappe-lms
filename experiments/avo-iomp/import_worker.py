"""Process a batch serially, with one in-memory IOMP connection."""

from contextlib import ExitStack, closing, nullcontext
import json
from pathlib import Path
import re
import sys

from import_capture import ACCOUNT, ARCHIVE, IompClient, WORKSPACE, main


def serve(requests, responses, *, import_course=main, connect=IompClient):
    with ExitStack() as lifetime:
        client = None

        def client_scope():
            nonlocal client
            if client is None:
                client = lifetime.enter_context(closing(connect(WORKSPACE)))
            return nullcontext(client)

        while line := requests.readline(65537):
            if len(line) > 65536 or not line.endswith(b'\n'):
                raise ValueError('invalid_worker_request')
            request = json.loads(line)
            if (not isinstance(request, dict)
                    or set(request) not in ({'course_id', 'directory'}, {'course_id', 'directory', 'resume_empty'})
                    or type(request.get('resume_empty', False)) is not bool):
                raise ValueError('invalid_worker_request')
            cid, directory = request['course_id'], request['directory']
            if (not isinstance(cid, str) or not re.fullmatch(r'[1-9][0-9]{0,9}', cid)
                    or not isinstance(directory, str)
                    or Path(directory).resolve().parent != ARCHIVE.resolve() / f'course-{cid}'):
                raise ValueError('invalid_worker_request')

            result = import_course(directory, require_empty=request.get('resume_empty', False),
                                   client_scope=client_scope)
            if result.get('course_id') != cid or result.get('status') not in ('imported', 'excluded', 'review', 'stopped'):
                raise ValueError('invalid_worker_result')
            print(json.dumps({'account': ACCOUNT, **result}, ensure_ascii=True), file=responses, flush=True)
            if result['status'] == 'stopped':
                break


if __name__ == '__main__':
    try:
        serve(sys.stdin.buffer, sys.stdout)
    except Exception:
        sys.exit(1)
