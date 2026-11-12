"""Read-only aggregate job status; never display source bodies or credentials."""
import json
from pathlib import Path
import sqlite3
import os
from contextlib import closing

ROOT = Path(os.environ.get('MASTER_VISION_WORKSPACE', str(Path(__file__).resolve().parents[3]))).resolve()
PATH = ROOT / 'exports/lesson-content/mastervision-migration/mastervision-migration.sqlite'


def status(path=PATH):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        rows = db.execute('SELECT account,origin,site FROM meta').fetchall()
        if rows != [('mastervision', 'https://shop.mastervision.su', 'my-lk.mastervision.su')]:
            raise ValueError('status_account_mismatch')
        states = dict(db.execute('SELECT state,COUNT(*) FROM courses GROUP BY state'))
        checkpoints = db.execute('SELECT lesson_digests FROM course_checkpoints').fetchall()
        last = db.execute('SELECT at,stage,course,lesson,status FROM events ORDER BY id DESC LIMIT 1').fetchone()
        return {'courses': states, 'catalog_courses': sum(states.values()), 'completed_source_courses': len(checkpoints),
                'completed_source_lessons': sum(len(json.loads(row[0])) for row in checkpoints),
                'errors': dict(db.execute('SELECT stage,consecutive FROM errors')),
                'last_event': dict(zip(('at_utc', 'stage', 'course', 'lesson', 'status'), last)) if last else None}


if __name__ == '__main__':
    try:
        print(json.dumps(status(), ensure_ascii=False))
    except Exception:
        print(json.dumps({'status': 'unavailable'}))
        raise SystemExit(1)
