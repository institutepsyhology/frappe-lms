"""Retry previously blocked MV-Centr courses; retain the importer's stop rules."""
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
from frappe_batch_import import EXCLUDED_COURSES

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / 'exports/lesson-content/mv-centr-frappe-import.sqlite'
IMPORT = Path(__file__).with_name('frappe_batch_import.py')

def state_and_candidates():
    with closing(sqlite3.connect(DATA.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        state=db.execute('select account,paused,consecutive_errors from state where singleton=1').fetchone()
        if not state or state[0]!='mv-centr': raise ValueError('wrong_account')
        latest={}
        for cid,status in db.execute("select course_id,status from events where course_id is not null and status in ('course_needs_review','course_created','course_ready','existing_structure_unverified') order by id"):
            latest[cid]=status
        return state, sorted(cid for cid,status in latest.items() if status=='course_needs_review' and cid not in EXCLUDED_COURSES)

def main():
    state,courses=state_and_candidates()
    if state[1]:
        print('Перенос на паузе; необходимо разобрать журнал.',flush=True)
        return 1
    print(f'Повторная проверка отложенных курсов: {len(courses)}.',flush=True)
    for cid in courses:
        state,_=state_and_candidates()
        if state[1]:
            print('Остановлено по порогу проблем; подробности в отчёте.',flush=True)
            return 1
        result=subprocess.run([sys.executable,str(IMPORT),'--apply','--course',str(cid)])
        if result.returncode:
            print(f'Остановлено на курсе {cid}; проверьте журнал.',flush=True)
            return result.returncode
    print('Повторная обработка списка завершена.',flush=True)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
