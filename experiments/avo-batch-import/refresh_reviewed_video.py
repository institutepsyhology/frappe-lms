"""Save owner-requested AVO updates only when the video additions are isolated."""
import copy, json, sqlite3, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'collector/lesson_content'))
sys.path.insert(0,str(ROOT/'frappe-mcp-avo'))
from batch import single_worker
from capture_store import CaptureStore, ORIGIN
from page_extract import parse_editor_page
from standalone_worker import packed_from_html
from lms.lms.avo_transform import _player_url

def normalized(root):
    root=copy.deepcopy(root); videos=[]
    def walk(v):
        if isinstance(v,dict):
            v.pop('id',None)
            v.pop('style',None)  # layout settings are not transferred
            if v.get('name')=='video':
                f=v.get('fields',{})
                for suffix in ('','2'):
                    provider=f.get('videoProvider'+suffix)
                    if provider=='rutube':
                        url=f.get('videoSrc'+suffix)
                        if suffix and not url:
                            f.pop('videoProvider'+suffix,None)
                            f.pop('videoSrc'+suffix,None)
                            f.pop('isShowProgressControl2',None)
                            f.pop('isShowFastRewindButtons2',None)
                        else:
                            videos.append(url)
                            f['videoSrc'+suffix]='__RUTUBE__'
            for x in v.values(): walk(x)
            for k in list(v):
                if v[k] in (None,'',False,[],{}):v.pop(k)
        elif isinstance(v,list):
            for x in v: walk(x)
    walk(root);return root,videos

def differences(a,b,path='root'):
    if type(a)!=type(b):return [path+':type']
    if isinstance(a,dict):
        result=[path+'.'+str(k)+':missing' for k in set(a)^set(b)]
        for k in a.keys() & b.keys():result.extend(differences(a[k],b[k],path+'.'+str(k)))
        return result
    if isinstance(a,list):
        if len(a)!=len(b):return [path+':length']
        return [p for i,(x,y) in enumerate(zip(a,b)) for p in differences(x,y,path+'['+str(i)+']')]
    return [] if a==b else [path+':changed']

def inventory(root):
    rows=[]
    def walk(v):
        if isinstance(v,dict):
            if v.get('name')=='video':
                f=v.get('fields') or {}
                rows.append([(f.get('videoProvider'+s),bool(f.get('videoSrc'+s)),
                    _player_url(f.get('videoSrc'+s),f.get('videoProvider'+s)) if f.get('videoProvider'+s) in ('youtube','rutube') else False) for s in ('','2')])
            for x in v.values():walk(x)
        elif isinstance(v,list):
            for x in v:walk(x)
    walk(root);return rows

def main():
    sys.stdin.reconfigure(encoding='utf-8')
    x=json.load(sys.stdin); cid=x['course_id']; lid=x['lesson_id']
    if cid!=889 or lid not in (8580,8581,8582):raise ValueError('invalid_identity')
    parsed=parse_editor_page(x['html'],ORIGIN,lid,cid)
    new=parsed['decoded']['json']
    with single_worker():
        with sqlite3.connect(ROOT/'exports/lesson-content/mv-centr-queue.sqlite') as q:
            if q.execute('select origin,paused from queue_meta where singleton=1').fetchone()!=(ORIGIN,0):raise ValueError('queue_not_ready')
            if q.execute('select state from queue_items where course_id=? and lesson_id=?',(cid,lid)).fetchone()!=('candidate',):raise ValueError('not_candidate')
        store=CaptureStore()
        try:
            row=store.db.execute('select decoded_json from captures where account=? and course_id=? and lesson_id=? and decoded_json is not null order by id desc limit 1',('mv-centr',cid,lid)).fetchone()
            if not row:raise ValueError('snapshot_missing')
            old,old_urls=normalized(json.loads(row[0])); fresh,new_urls=normalized(new)
            if old!=fresh or len(old_urls)!=1 or len(new_urls)!=1 or old_urls[0] not in ('',None) or not _player_url(new_urls[0],'rutube'):
                print(json.dumps({'lesson':lid,'changed_paths':differences(old,fresh)[:5],
                    'old_rutube_count':len(old_urls),'new_rutube_count':len(new_urls),
                    'old_videos':inventory(json.loads(row[0])),'new_videos':inventory(new)}))
                raise ValueError('unexpected_source_change')
            saved=store.save({'account':'mv-centr','account_origin':ORIGIN,'course_id':cid,'lesson_id':lid,'packed':packed_from_html(x['html'])})
            if saved['diagnostic_code']!='requires_independent_verification':raise ValueError('snapshot_not_usable')
            print(json.dumps({'lesson':lid,'saved':not saved['duplicate'],'rutube_valid':True}))
        finally:store.close()
if __name__=='__main__':
    try:main()
    except Exception as e:
        print(json.dumps({'error':str(e) if str(e) in ('invalid_identity','queue_not_ready','not_candidate','snapshot_missing','unexpected_source_change','snapshot_not_usable') else 'refresh_failed'}))
        sys.exit(1)
