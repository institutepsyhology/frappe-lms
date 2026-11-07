"""Private SSH journal worker: accepts only diagnostic events, never lessons."""
import json
import os
import sys

os.environ['AVO_REMOTE_JOURNAL_WORKER']='1'
from frappe_batch_import import Journal, DATA, REPORT, PROBLEMS_REPORT, EXCLUDED_COURSES

def main():
    journal=Journal(DATA/'mv-centr-frappe-import.sqlite')
    try:
        for line in sys.stdin:
            try:
                req=json.loads(line)
                if not isinstance(req,dict) or set(req)!={'method','args'} or not isinstance(req['args'],list):
                    raise ValueError('invalid_request')
                method,args=req['method'],req['args']
                if method=='ping':result={'account':'mv-centr'}
                elif method=='state':result=journal.state()
                elif method=='event':
                    if (len(args) not in (3,4) or any(x is not None and (type(x) is not int or x<1) for x in args[:2])
                            or not isinstance(args[2],str) or (len(args)==4 and not isinstance(args[3],list))):
                        raise ValueError('invalid_event')
                    result=journal.event(*args)
                elif method=='resume':result=journal.resume()
                elif method=='failure':result=journal.failure(*args)
                elif method=='success':result=journal.success()
                elif method=='candidates':
                    latest={}
                    for cid,status in journal.db.execute("select course_id,status from events where course_id is not null and status in ('course_needs_review','course_created','course_ready','existing_structure_unverified') order by id"):
                        latest[cid]=status
                    result=sorted(cid for cid,status in latest.items() if status=='course_needs_review' and cid not in EXCLUDED_COURSES)
                elif method=='report':
                    journal.report()
                    result={'report':REPORT.read_text(encoding='utf-8'),
                            'problems':PROBLEMS_REPORT.read_text(encoding='utf-8')}
                elif method=='close':result=None
                else:raise ValueError('unknown_method')
                print(json.dumps({'ok':True,'result':result},ensure_ascii=True),flush=True)
                if method=='close':break
            except Exception:
                print(json.dumps({'ok':False,'error':'journal_operation_failed'}),flush=True)
    finally:journal.close()

if __name__=='__main__':main()
