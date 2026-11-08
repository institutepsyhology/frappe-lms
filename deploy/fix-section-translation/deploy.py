import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path

root = Path('/opt/company-lms/runtime')
env = root / '.env'
old = 'sha256:43232c39d44bb06c9b136cc91e88ee1375aa4f3e48228da4ec709d263720df9f'
tag = 'company-lms:section-translation-d4d748a9'
services = ['backend', 'frontend', 'queue-long', 'queue-short', 'scheduler', 'websocket']
compose = ['docker', 'compose', '--project-directory', str(root), '-f', str(root / 'compose.yaml')]
new = subprocess.check_output(['docker', 'image', 'inspect', tag, '--format', '{{.Id}}'], text=True).strip()
original = env.read_bytes()
if re.findall(rb'(?m)^LMS_IMAGE=(.+)$', original) != [old.encode()]:
    raise SystemExit('Runtime image changed; refusing deployment')
backup = root / '.env.before-section-translation-d4d748a9'
fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'wb') as f:
    f.write(original)

def replace(data):
    temp = root / '.env.section-translation-tmp'
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(data)
    os.replace(temp, env)

def up():
    subprocess.run(compose + ['up', '-d', '--no-deps'] + services, check=True, timeout=180)

def verify(image):
    ids = subprocess.check_output(compose + ['ps', '-q'] + services, text=True).split()
    if len(ids) != len(services):
        return False
    import json
    states = json.loads(subprocess.check_output(['docker', 'inspect'] + ids, text=True))
    if not all(s['Image'] == image and s['State']['Running'] and not s['State']['OOMKilled'] for s in states):
        return False
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for host in ['my-lk.mv-centr.ru', 'my-lk.iomp.ru', 'my-lk.mastervision.su']:
        with opener.open('https://' + host + '/api/method/ping', timeout=10) as response:
            if json.load(response).get('message') != 'pong':
                return False
    return True

try:
    replace(re.sub(rb'(?m)^LMS_IMAGE=.+$', b'LMS_IMAGE=' + new.encode(), original))
    up()
    for site in ['my-lk.mv-centr.ru', 'my-lk.iomp.ru', 'my-lk.mastervision.su']:
        subprocess.run(compose + ['exec', '-T', 'backend', 'bench', '--site', site, 'clear-cache'], check=True, timeout=60)
    for attempt in range(20):
        try:
            if verify(new):
                print('DEPLOY_OK', new)
                break
        except Exception:
            pass
        time.sleep(3)
    else:
        raise RuntimeError('Verification failed')
except Exception:
    replace(original)
    up()
    print('ROLLED_BACK', old)
    raise
