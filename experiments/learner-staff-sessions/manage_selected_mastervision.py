"""Prepare one MV CSV selection or hand its API key to the server in memory."""
import argparse
import json
from pathlib import Path
import queue
import re
import shlex
import subprocess
import threading

HERE=Path(__file__).resolve().parent
WORKSPACE=HERE.parents[2]
BENCH='/home/frappe/frappe-bench'
SITE='my-lk.mastervision.su'

PREPARE=r'''
import hashlib,json,os,sqlite3,sys
from pathlib import Path
request=json.loads(sys.stdin.buffer.read(32*1024**2+1))
assert set(request)=={'release','selection'}
revision=request['release'];assert len(revision)==40 and all(c in '0123456789abcdef' for c in revision)
root=Path('/home/frappe/frappe-bench/sites/my-lk.mastervision.su/private')
release=root/'apply-avo-contacts'/('release-'+revision)
sys.path.insert(0,str(release))
import apply_server_contacts as worker
assert worker.verify_release()==revision
selection=request['selection'];ids,digest=worker.validate_selection(selection)
parent=root/'selected-contacts';worker.private(parent)
folder=worker.selection_path(digest);worker.private(folder)
path=worker.safe_file(folder/'selection.json')
if path.exists():assert json.loads(path.read_text())==selection
else:
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as stream:
  json.dump(selection,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
assert worker.read_selection('mastervision',digest)[0]==ids
path=worker.safe_file(folder/'contacts.sqlite')
fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);os.close(fd)
with sqlite3.connect(path) as db:
 db.execute('PRAGMA synchronous=FULL')
 db.execute('CREATE TABLE IF NOT EXISTS contacts(id INTEGER PRIMARY KEY,record_json TEXT NOT NULL)')
 if db.execute('SELECT COUNT(*) FROM contacts').fetchone()[0]==0:
  db.executemany('INSERT INTO contacts VALUES (?,?)',((i,json.dumps({'source':'https://shop.mastervision.su','contact':{'id':i}})) for i in selection['ids']))
 actual={str(row[0]) for row in db.execute('SELECT id FROM contacts')}
 assert actual==ids
print(json.dumps({'prepared':True,'account':'mastervision','site':'my-lk.mastervision.su','selection':digest,'total':len(ids),'release':revision}))
'''


def command(release,*,selection=None,prepare=False):
    if type(release) is not str or not re.fullmatch('[a-f0-9]{40}',release):raise ValueError('invalid_release')
    if not prepare and (type(selection) is not str or not re.fullmatch('[a-f0-9]{64}',selection)):
        raise ValueError('invalid_selection')
    remote=['docker','exec','-i','-u','frappe','-w',BENCH+'/sites','company-lms-backend-1',BENCH+'/env/bin/python','-B']
    if prepare:remote.extend(['-c',PREPARE])
    else:remote.extend([BENCH+'/sites/'+SITE+'/private/apply-avo-contacts/release-'+release+
        '/selected_mastervision_links.py','--start','--selection',selection])
    return [r'C:\Windows\System32\OpenSSH\ssh.exe','-o','BatchMode=yes','-o','ConnectTimeout=15',
        '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(WORKSPACE/'frappe-deploy/known_hosts'),
        '-i',str(Path.home()/'.ssh/codex_timeweb_lms_20261010'),'root@89.223.71.30',shlex.join(remote)]


def start_links(release,selection,key):
    from launch_mastervision_archive import validated_key
    secret=validated_key(key)
    try:
        result=subprocess.run(command(release,selection=selection),input=json.dumps({'key':secret}).encode(),
            capture_output=True,timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        response=json.loads(result.stdout) if len(result.stdout)<4096 else {}
        if (result.returncode or response.get('status')!='starting' or response.get('account')!='mastervision'
                or response.get('site')!=SITE or response.get('key_saved') is not False
                or type(response.get('worker_pid')) is not int):raise ValueError('start_not_confirmed')
        return response
    finally:secret=None


def graphical(release,selection):
    import tkinter as tk
    from tkinter import ttk,messagebox
    root=tk.Tk();root.withdraw();root.title('МВ — ссылки для контактов из трёх выгрузок')
    frame=ttk.Frame(root,padding=20);frame.grid()
    ttk.Label(frame,text='Только контакты выбранных выгрузок МВ',font=('',12)).grid(sticky='w')
    ttk.Label(frame,text='Источник: shop.mastervision.su\nНазначение: my-lk.mastervision.su\n'
        'Общий перенос МВ и ИОМП остаётся на паузе.\n'
        'Ключ передаётся по защищённому соединению и хранится только в памяти.\n'
        'Ссылки и карточки сохраняются на сервере; на ноутбук не скачиваются.').grid(sticky='w',pady=10)
    ttk.Label(frame,text='API KEY GET именно Master Vision:').grid(sticky='w')
    entry=ttk.Entry(frame,width=65,show='*');entry.grid(sticky='ew',pady=6)
    status=ttk.Label(frame,text='Ожидаю ключ. Перенос из готового API-архива работает отдельно.');status.grid(sticky='w',pady=10)
    messages=queue.Queue();active=False
    def submit():
        nonlocal active
        from launch_mastervision_archive import validated_key
        try:secret=validated_key(entry.get())
        except Exception:
            messagebox.showerror('Проверьте ключ','Введите API KEY GET аккаунта Master Vision.',parent=root);return
        entry.delete(0,'end');entry.configure(state='disabled');button.configure(state='disabled');active=True
        status.configure(text='Запускаю сбор персональных ссылок на сервере…')
        def background():
            nonlocal secret
            try:messages.put(('ok',start_links(release,selection,secret)))
            except Exception:messages.put(('error',None))
            finally:secret=None
        threading.Thread(target=background,daemon=False).start()
    def poll():
        nonlocal active
        try:
            kind,value=messages.get_nowait();active=False
            if kind=='ok':
                status.configure(text='Сбор персональных ссылок запущен. Окно можно закрыть.')
                root.after(2500,root.destroy);return
            status.configure(text='Запуск не подтверждён. Ключ не сохранён; проверяем состояние сервера.')
        except queue.Empty:pass
        root.after(150,poll)
    def close():
        if active:status.configure(text='Ожидаю ответ сервера…')
        else:root.destroy()
    button=ttk.Button(frame,text='Запустить сбор ссылок выбранных контактов МВ',command=submit);button.grid(sticky='e')
    root.protocol('WM_DELETE_WINDOW',close);root.update_idletasks()
    root.geometry('+'+str(max(0,(root.winfo_screenwidth()-root.winfo_reqwidth())//2))+'+'
        +str(max(0,(root.winfo_screenheight()-root.winfo_reqheight())//2)))
    root.attributes('-topmost',True);root.deiconify();entry.focus_force()
    root.after(1500,lambda:root.attributes('-topmost',False));root.after(150,poll);root.mainloop()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',required=True)
    parser.add_argument('--files',nargs='+',type=Path)
    parser.add_argument('--key-window',action='store_true');parser.add_argument('--selection')
    args=parser.parse_args()
    if args.key_window:
        command(args.release,selection=args.selection);graphical(args.release,args.selection)
    elif args.files:
        from contact_selection import build_selection
        selection=build_selection(args.files)
        result=subprocess.run(command(args.release,prepare=True),
            input=json.dumps({'release':args.release,'selection':selection}).encode(),
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=90)
        if result.returncode:raise SystemExit('selection_prepare_failed')
        response=json.loads(result.stdout)
        if (response.get('prepared') is not True or response.get('total')!=selection['manifest']['union_count']
                or response.get('selection')!=selection['manifest']['fingerprint']):
            raise SystemExit('selection_prepare_unverified')
        print(json.dumps(response))
    else:raise SystemExit('explicit_action_required')


if __name__=='__main__':main()
