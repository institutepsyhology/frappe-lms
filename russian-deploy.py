"""Deploy this tested localization image on the existing three-site LMS host.

Run as root on the configured host. Backs up the runtime environment, changes
only LMS_IMAGE, recreates application services, and verifies HTTPS. On failure
the previous image is restored. No database migration or content edit is run.
"""
import datetime
import http.cookiejar
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

BASE=Path('/opt/company-lms')
SITES=['my-lk.mastervision.su','my-lk.iomp.ru','my-lk.mv-centr.ru']
SERVICES=['backend','frontend','websocket','queue-short','queue-long','scheduler']
COMPOSE=['docker','compose','--project-directory',str(BASE/'runtime'),'--profile','jobs']
OLD='sha256:30a77dba1c33dcd3e221c17a54806dc5ac64f718a11093e3186dc1cfc23653dc'
NEW='sha256:35b5b3e30e863b5b4488ee4c60345cebb742cfe4096aa2f582fcd4d62f31229b'
CODE=r'''
import os,json
os.chdir('/home/frappe/frappe-bench/sites')
import frappe
from frappe import translate
results=[]
for site in ['my-lk.mastervision.su','my-lk.iomp.ru','my-lk.mv-centr.ru']:
 try:
  frappe.init(site=site);frappe.connect();frappe.set_user('Administrator')
  frappe.clear_cache();translate.clear_cache()
  results.append({'site':site,'language':frappe.db.get_single_value('System Settings','language'),'counts':{dt:frappe.db.count(dt) for dt in ['User','LMS Course','Course Chapter','Course Lesson','LMS Enrollment']}})
 finally:frappe.destroy()
print('DEPLOY_STATE:'+json.dumps(results))
'''


def snapshot():
    result=subprocess.run(COMPOSE+['exec','-T','backend','env/bin/python','-c',CODE],capture_output=True,text=True,timeout=50)
    rows=[line.removeprefix('DEPLOY_STATE:') for line in result.stdout.splitlines() if line.startswith('DEPLOY_STATE:')]
    if result.returncode or len(rows)!=1:raise RuntimeError('CannotReadSiteState')
    return json.loads(rows[0])


def write_new(path,data):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as f:f.write(data)


def up():
    result=subprocess.run(COMPOSE+['up','-d','--no-deps']+SERVICES,capture_output=True,text=True,timeout=120)
    if result.returncode:raise RuntimeError('ApplicationRecreateFailed')


def services_healthy(image):
    ids=subprocess.check_output(COMPOSE+['ps','-q']+SERVICES,text=True).split()
    if len(ids)!=len(SERVICES):return False
    states=json.loads(subprocess.check_output(['docker','inspect']+ids,text=True))
    return all(v['Image']==image and v['State']['Running'] and not v['State']['OOMKilled'] for v in states)


def ping(site):
    client=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    try:
        with client.open('https://'+site+'/api/method/ping',timeout=8) as response:
            return response.code==200 and json.load(response).get('message')=='pong'
    except Exception:return False


def verify_http(site):
    root='https://'+site
    jar=http.cookiejar.CookieJar()
    client=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(jar),urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    def request(path,form=None):
        data=urllib.parse.urlencode(form).encode() if form else None
        req=urllib.request.Request(root+path,data=data,headers={'User-Agent':'LMS-Russian-Deployment-Verification','Accept-Language':'ru-RU,ru;q=0.9'})
        try:response=client.open(req,timeout=15)
        except urllib.error.HTTPError as error:response=error
        with response:return response.code,response.read(4*1024*1024)
    checks={}
    try:
        code,body=request('/api/method/lms.lms.api.get_translations')
        catalog=json.loads(body).get('message',{})
        checks['guest_new_catalog']=code==200 and catalog.get('Learning')=='Обучение' and catalog.get('No {0} Found')=='Раздел «{0}» пока пуст'
        credential=BASE/'secrets'/('site-'+site+'-admin-password')
        if credential.is_symlink() or credential.stat().st_uid!=0 or credential.stat().st_mode&0o077:raise RuntimeError('UnsafeCredentialFile')
        code,body=request('/api/method/login',{'usr':'Administrator','pwd':credential.read_text().strip()})
        checks['administrator_login']=code==200
        code,body=request('/api/method/frappe.auth.get_logged_user')
        checks['administrator_identity']=code==200 and json.loads(body).get('message')=='Administrator'
        code,body=request('/api/method/lms.lms.api.get_translations')
        catalog=json.loads(body).get('message',{})
        checks['authenticated_new_catalog']=code==200 and catalog.get('Learning')=='Обучение' and catalog.get('Rewind {0} seconds')=='Назад на {0} с'
        code,body=request('/lms/courses')
        checks['lms_html_ru']=code==200 and b'lang="ru"' in body
        assets=re.findall(rb'<script[^>]+src="([^"]+)"',body)
        modules=[p.decode() for p in assets if p.startswith(b'/assets/lms/frontend/assets/') and p.endswith(b'.js')]
        checks['compiled_js_available']=bool(modules) and all(request(path)[0]==200 for path in modules)
        code,body=request('/desk')
        checks['desk_html_ru']=code==200 and b'lang="ru"' in body
        return {'site':site,'dictionary_entries':len(catalog),'checks':checks}
    finally:
        try:request('/api/method/logout')
        except Exception:pass
        jar.clear()


if __name__=='__main__':
    if os.geteuid()!=0 or subprocess.check_output(['hostname'],text=True).strip()!='spb-3-vm-t6fa':raise RuntimeError('UnexpectedHost')
    actual=subprocess.check_output(['docker','image','inspect','company-lms:russian-2.64.0-20261024','--format','{{.Id}}'],text=True).strip()
    if actual!=NEW:raise RuntimeError('UnexpectedLocalizedImage')
    env=BASE/'runtime/.env';original=env.read_bytes()
    old_lines=re.findall(rb'^LMS_IMAGE=(.+)$',original,re.M)
    if len(old_lines)!=1 or old_lines[0].strip().decode()!=OLD:raise RuntimeError('RuntimeImageChangedSinceReview')
    before=snapshot()
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup=BASE/'backups'/('russian-release-'+stamp);backup.mkdir(mode=0o700)
    write_new(backup/'runtime.env.before',original)
    write_new(backup/'site-counts.before.json',(json.dumps(before)+'\n').encode())
    updated=re.sub(rb'(?m)^LMS_IMAGE=.+$',('LMS_IMAGE='+NEW).encode(),original)
    report={'previous_image':OLD,'image':NEW,'backup_directory':str(backup),'ok':False}
    try:
        temporary=env.with_name('.env.russian-'+stamp);write_new(temporary,updated);os.replace(temporary,env)
        up()
        deadline=time.monotonic()+90
        while True:
            try:after=snapshot();break
            except Exception:
                if time.monotonic()>=deadline:raise
                time.sleep(2)
        report['counts_and_language_unchanged']=after==before
        if any(a['language']!=b['language'] or any(a['counts'][dt]<b['counts'][dt] for dt in b['counts']) for a,b in zip(after,before)):raise RuntimeError('SiteCountsDecreasedOrLanguageChanged')
        report['counts_not_decreased']=True
        while True:
            try:
                report['sites']=[verify_http(site) for site in SITES]
                if all(all(v['checks'].values()) for v in report['sites']):break
            except Exception:
                if time.monotonic()>=deadline:raise
            if time.monotonic()>=deadline:raise RuntimeError('HTTPVerificationFailed')
            time.sleep(2)
        report['application_services_healthy']=services_healthy(NEW)
        report['ok']=report['application_services_healthy'] and all(all(v['checks'].values()) for v in report['sites'])
        if not report['ok']:raise RuntimeError('LocalizedReleaseVerificationFailed')
    except Exception as error:
        report['error']=type(error).__name__
        if type(error) is RuntimeError:report['detail']=str(error)
        # Restore the exact bytes saved by this run, then recreate the old apps.
        temporary=env.with_name('.env.rollback-'+stamp);write_new(temporary,original);os.replace(temporary,env)
        try:
            up();deadline=time.monotonic()+90
            while not (services_healthy(OLD) and all(ping(site) for site in SITES)):
                if time.monotonic()>=deadline:raise RuntimeError('RollbackRecoveryFailed')
                time.sleep(2)
            snapshot()
            report['rolled_back']=True
        except Exception:report['rolled_back']=False
    report['completed_at_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    write_new(backup/'result.json',(json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode())
    print(json.dumps(report,ensure_ascii=False))
    raise SystemExit(0 if report['ok'] else 1)
