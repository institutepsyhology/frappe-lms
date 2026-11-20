"""Run the verified, finite MV access import in the site's private directory."""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys

from target_archive import complete_archive, require

HERE = Path(__file__).resolve().parent
DATA = Path('/home/frappe/frappe-bench/sites/my-lk.mastervision.su/private/mv-course-access/through-446858-20261120')
ARCHIVE = DATA / 'cards.sqlite'
RULES = DATA / 'rules.json'


def mark(stage, **counts):
    payload = dict(stage=stage, updated_at=datetime.now(timezone.utc).isoformat(), **counts)
    file = DATA / 'apply-state.tmp'
    file.write_text(json.dumps(payload))
    file.replace(DATA / 'apply-state.json')


def run():
    with complete_archive(ARCHIVE) as db:
        courses = db.execute('SELECT COUNT(DISTINCT course_id) FROM cards').fetchone()[0]
        require(courses > 0, 'no_courses')
    mark('reading_course_settings', courses=courses)
    with (DATA/'policy-review.jsonl').open('w') as log:
        subprocess.run([sys.executable, '-B', str(HERE/'course_rules.py'), '--fresh-dir', str(DATA/'policies'),
                        '--out', str(RULES)], check=True, stdout=log, stderr=log)
    pool = json.loads(RULES.read_text())['courses']
    control = pool['598']
    require(control['permanent_lesson_access'] is False and control['show_when_unavailable'] == 1
            and control.get('access_notice_content'), 'control_rule_changed')
    require(not control['draft_lesson_ids'] or 6518 not in control['draft_lesson_ids'], 'control_renewal_draft')
    mark('syncing', courses=courses, confirmed_settings=len(pool))
    with (DATA/'apply.jsonl').open('a', buffering=1) as log:
        proc = subprocess.run([sys.executable, '-B', str(HERE/'target_sync.py'), '--archive', str(ARCHIVE),
                               '--rules', str(RULES), '--apply'], stdout=log, stderr=log)
    mark({0:'complete',2:'review'}.get(proc.returncode,'stopped'), exit_code=proc.returncode)
    return proc.returncode


if __name__ == '__main__':
    os.umask(0o077)
    with (DATA/'apply.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with (DATA/'apply.log').open('a', buffering=1) as out, redirect_stdout(out), redirect_stderr(out):
            try:
                sys.exit(run())
            except Exception as error:
                mark('stopped', reason=type(error).__name__)
                raise
