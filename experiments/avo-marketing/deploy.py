"""Activate the verified contact-card image with backups and image rollback.

Run as root on the LMS host after prepare_sites.py and while bulk imports are
paused. Existing site data and encryption keys are never deleted on rollback.
"""
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request

BASE=Path('/opt/company-lms')
RUNTIME=BASE/'runtime'
BACKEND='company-lms-backend-1'
SITES=('my-lk.mv-centr.ru','my-lk.iomp.ru','my-lk.mastervision.su')
SERVICES=('backend','frontend','websocket','queue-short','queue-long','scheduler')
COMPOSE=['docker','compose','--project-directory',str(RUNTIME),'--profile','jobs']
OLD='sha256:3831530e82848dc458dd8d88e8169821cbbfa87dde75089049084c8c9959f431'
TAG='company-lms:marketing-20261111-v2'
NEW='sha256:13d25c60100985c6042644cb83a5aa2e15275bbaa61cd5abc1b8dd82dac523fc'
BENCH='/home/frappe/frappe-bench'


def run(args,timeout=120):
    p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout)
    if p.returncode:raise RuntimeError('command_failed:'+str(p.returncode))
    return p.stdout.strip()


def safe_write(path, data):
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())


def state():
    code='''import frappe,json\nsites=["my-lk.mv-centr.ru","my-lk.iomp.ru","my-lk.mastervision.su"];out=[]\nfor s in sites:\n frappe.init(site=s);frappe.connect()\n try: out.append({"site":s,"counts":{d:frappe.db.count(d) for d in ["User","Contact","LMS Course","Course Lesson","LMS Enrollment"]}})\n finally: frappe.destroy()\nprint(json.dumps(out))\n'''
    return json.loads(run(['docker','exec','-u','frappe','-w',BENCH+'/sites',BACKEND,BENCH+'/env/bin/python','-c',code]))


def healthy(image):
    ids=run(COMPOSE+['ps','-q',*SERVICES]).splitlines()
    if len(ids)!=len(SERVICES):return False
    rows=json.loads(run(['docker','inspect',*ids]))
    return all(row['Image']==image and row['State']['Running'] and not row['State']['OOMKilled'] for row in rows)


def ping(site):
    client=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with client.open('https://'+site+'/api/method/ping',timeout=8) as r:
            return r.status==200 and json.load(r).get('message')=='pong'
    except Exception:return False


def setup_sites():
    code='''import frappe,json,sys\nfrom frappe import translate\nfrom lms.lms.support_credentials import ensure_role\nfrom lms.lms.avo_contact_fields import execute as user_fields\nfrom lms.lms.avo_contact_identity import execute as contact_fields\ns=sys.argv[1];frappe.init(site=s);frappe.connect();frappe.set_user("Administrator")\ntry:\n if not frappe.conf.get("encryption_key"): raise RuntimeError("missing_encryption_key")\n ensure_role();user_fields();contact_fields();frappe.db.commit();frappe.clear_cache();translate.clear_cache()\n u=frappe.get_meta("User");c=frappe.get_meta("Contact")\n result={"site":s,"role":bool(frappe.db.exists("Role","LMS Credential Manager")),"user_fields":all(u.has_field(x) for x in ["custom_avo_contact_id","custom_avo_account","custom_avo_telegram_id","custom_avo_vk_id","custom_no_marketing_email"]),"contact_fields":all(c.has_field(x) for x in ["custom_avo_contact_id","custom_avo_account","custom_avo_telegram_id","custom_avo_vk_id","custom_no_marketing_email"]),"key":bool(frappe.conf.get("encryption_key"))}\n if not all(v for k,v in result.items() if k!="site"):raise RuntimeError("setup_verification_failed")\n print(json.dumps(result))\nfinally: frappe.destroy()\n'''
    return [json.loads(run(['docker','exec','-u','frappe','-w',BENCH+'/sites',BACKEND,
        BENCH+'/env/bin/python','-c',code,site],timeout=180)) for site in SITES]


def main():
    if os.geteuid()!=0 or run(['hostname'])!='spb-3-vm-t6fa':raise RuntimeError('unexpected_host_or_user')
    old=run(['docker','inspect','--format','{{.Image}}',BACKEND])
    if old!=OLD or not healthy(OLD):raise RuntimeError('active_image_changed')
    new=run(['docker','image','inspect',TAG,'--format','{{.Id}}'])
    if new!=NEW or not re.fullmatch(r'sha256:[0-9a-f]{64}',new) or new==OLD:raise RuntimeError('candidate_image_missing')
    backups=sorted((BASE/'backups').glob('contact-card-*/manifest.json'))
    if not backups:raise RuntimeError('prepared_backups_missing')
    backup=json.loads(backups[-1].read_text(encoding='utf-8'))
    if {row['site'] for row in backup.get('sites',[])}!=set(SITES) or not all(row['gzip_verified'] and row['key_saved'] for row in backup['sites']):
        raise RuntimeError('prepared_backups_invalid')
    env=RUNTIME/'.env';original=env.read_bytes()
    lines=re.findall(rb'(?m)^LMS_IMAGE=(.+)$',original)
    if len(lines)!=1 or lines[0].strip().decode()!=OLD:raise RuntimeError('runtime_image_changed')
    before=state()
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder=BASE/'backups'/('contact-card-deploy-'+stamp);folder.mkdir(mode=0o700)
    safe_write(folder/'runtime.env.before',original)
    safe_write(folder/'counts.before.json',(json.dumps(before)+'\n').encode())
    report={'old':OLD,'new':new,'backup_manifest':str(backups[-1]),'ok':False}
    try:
        updated=re.sub(rb'(?m)^LMS_IMAGE=.+$',('LMS_IMAGE='+new).encode(),original)
        temp=env.with_name('.env.contact-card-'+stamp);safe_write(temp,updated);os.replace(temp,env)
        run(COMPOSE+['up','-d','--no-deps',*SERVICES],timeout=180)
        deadline=time.monotonic()+180
        while not healthy(new):
            if time.monotonic()>deadline:raise RuntimeError('services_not_ready')
            time.sleep(3)
        report['sites']=setup_sites()
        after=state()
        for prior,current in zip(before,after):
            if prior['site']!=current['site'] or any(current['counts'][key]<value for key,value in prior['counts'].items()):
                raise RuntimeError('site_counts_decreased')
        if not all(ping(site) for site in SITES):raise RuntimeError('site_ping_failed')
        report.update(ok=True,counts_not_decreased=True,services_healthy=True,ping_ok=True)
    except Exception as exc:
        report['error']=type(exc).__name__
        if isinstance(exc,RuntimeError):report['reason']=str(exc)
        temp=env.with_name('.env.contact-card-rollback-'+stamp);safe_write(temp,original);os.replace(temp,env)
        try:
            run(COMPOSE+['up','-d','--no-deps',*SERVICES],timeout=180)
            deadline=time.monotonic()+180
            while not (healthy(OLD) and all(ping(site) for site in SITES)):
                if time.monotonic()>deadline:raise RuntimeError('rollback_failed')
                time.sleep(3)
            report['rolled_back']=True
        except Exception:report['rolled_back']=False
    safe_write(folder/'result.json',(json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode())
    print(json.dumps(report,ensure_ascii=False),flush=True)
    return 0 if report['ok'] else 1


if __name__=='__main__':raise SystemExit(main())
