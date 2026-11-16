"""Masked MV key handoff to its detached server collector; no laptop data spool."""
import argparse
import json
import os
from pathlib import Path
import queue
import re
import shlex
import subprocess
import threading
from types import MappingProxyType

HERE=Path(__file__).resolve().parent
WORKSPACE=HERE.parents[2]
SITE='my-lk.mastervision.su'
REMOTE_BASE='/home/frappe/frappe-bench/sites/'+SITE+'/private/avo-api-archive'
ACCOUNTS=MappingProxyType({
    'mastervision':('my-lk.mastervision.su','https://shop.mastervision.su','МВ','Master Vision'),
    'iomp':('my-lk.iomp.ru','https://shop.iomp.ru','ИОМП','ИОМП'),
})


class LaunchError(Exception):pass


def account_settings(account):
    if not isinstance(account,str) or account not in ACCOUNTS:
        raise LaunchError('wrong_account')
    return ACCOUNTS[account]


def validated_key(value):
    if not isinstance(value,str):raise LaunchError('invalid_key_input')
    value=value.strip()
    if not 1<=len(value)<=512 or '://' in value or any(ord(c)<33 or ord(c)==127 for c in value):
        raise LaunchError('invalid_key_input')
    return value


def command(release,account='mastervision'):
    site,_,_,_=account_settings(account)
    if not isinstance(release,str) or not re.fullmatch('[a-f0-9]{40}',release):
        raise LaunchError('invalid_release')
    bench='/home/frappe/frappe-bench'
    remote_base=bench+'/sites/'+site+'/private/avo-api-archive'
    remote=shlex.join(['docker','exec','-i','-u','frappe','-w',bench+'/sites',
        '-e','AVO_SERVER_ARCHIVE_ACCOUNT='+account,
        'company-lms-backend-1',bench+'/env/bin/python','-B',
        remote_base+'/release-'+release+'/server_archive_job.py','--start'])
    return ['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15','-o','ServerAliveInterval=10',
        '-o','ServerAliveCountMax=2','-o','StrictHostKeyChecking=yes',
        '-o','UserKnownHostsFile='+str(WORKSPACE/'frappe-deploy/known_hosts'),
        '-i',str(Path.home()/'.ssh/codex_timeweb_lms_20261010'),'root@89.223.71.30',remote]


def start(release,key,account='mastervision'):
    site,_,_,_=account_settings(account)
    key=validated_key(key)
    try:
        result=subprocess.run(command(release,account),input=json.dumps({'key':key}).encode('utf-8'),
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=45,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if len(result.stdout)>4096:raise LaunchError('server_start_uncertain')
        response=json.loads(result.stdout)
        if (result.returncode or not isinstance(response,dict) or response.get('status') not in {'started','starting'}
                or response.get('site')!=site or response.get('account')!=account
                or response.get('key_saved') is not False or type(response.get('worker_pid')) is not int
                or response['worker_pid']<=0):
            raise LaunchError('server_start_not_confirmed')
        return response
    except (OSError,subprocess.SubprocessError,ValueError,UnicodeError):
        raise LaunchError('server_start_uncertain') from None
    finally:key=None


def graphical(release,account='mastervision'):
    site,origin,label,name=account_settings(account)
    import tkinter as tk
    from tkinter import ttk,messagebox
    root=tk.Tk();root.withdraw()
    root.title(label+' — сбор аккаунтов на сервере')
    frame=ttk.Frame(root,padding=20);frame.grid()
    ttk.Label(frame,text=name+': отдельный сбор на сервере',font=('',12)).grid(sticky='w')
    ttk.Label(frame,text='Источник: '+origin+'\n'
        'Сохранение: Frappe '+label+' — '+site+'\n'
        'На ноутбук контакты не скачиваются. Другие сборщики продолжают работу.\n'
        'Ключ передаётся по защищённому соединению и остаётся только\n'
        'в памяти серверного сборщика; в файлы и журналы не записывается.').grid(sticky='w',pady=10)
    ttk.Label(frame,text='API KEY GET именно аккаунта '+name+':').grid(sticky='w')
    entry=ttk.Entry(frame,width=70,show='*');entry.grid(sticky='ew',pady=6)
    status_label=ttk.Label(frame,text='Готов к запуску.');status_label.grid(sticky='w',pady=8)
    messages=queue.Queue();active=False
    def submit():
        nonlocal active
        try:secret=validated_key(entry.get())
        except LaunchError:
            messagebox.showerror('Проверьте ключ','Нужен API KEY GET '+label+', без адреса страницы.',parent=root);return
        entry.delete(0,'end');entry.configure(state='disabled');button.configure(state='disabled')
        active=True;status_label.configure(text='Запускаю на сервере '+label+'…')
        def worker():
            nonlocal secret
            try:messages.put(('ok',start(release,secret,account)))
            except Exception:messages.put(('error',None))
            finally:secret=None
        threading.Thread(target=worker,daemon=False).start()
    def poll():
        nonlocal active
        try:
            kind,value=messages.get_nowait();active=False
            if kind=='ok':
                status_label.configure(text='Сборщик запущен на сервере. Окно закроется автоматически.')
                root.after(2500,root.destroy);return
            status_label.configure(text='Запуск не подтверждён. Проверяю причину; ключ не сохранён.')
        except queue.Empty:pass
        root.after(150,poll)
    def close():
        if active:status_label.configure(text='Ожидаю подтверждения сервера…')
        else:root.destroy()
    button=ttk.Button(frame,text='Начать / продолжить сбор '+label+' на сервере',command=submit)
    button.grid(sticky='e',pady=6)
    root.protocol('WM_DELETE_WINDOW',close)
    root.update_idletasks()
    root.geometry('+'+str(max(0,(root.winfo_screenwidth()-root.winfo_reqwidth())//2))
        +'+'+str(max(0,(root.winfo_screenheight()-root.winfo_reqheight())//2)))
    root.attributes('-topmost',True);root.deiconify();root.lift();entry.focus_force()
    root.after(1500,lambda:root.attributes('-topmost',False));root.after(150,poll)
    root.mainloop()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',required=True)
    parser.add_argument('--account',choices=tuple(ACCOUNTS),default='mastervision')
    args=parser.parse_args()
    command(args.release,args.account)
    graphical(args.release,args.account)


if __name__=='__main__':main()
