import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path

root = Path('/opt/company-lms/runtime')
env = root / '.env'
old = 'sha256:b1b728a0f49e44e926cb6b03a82c6a70daecd5d8435452404b0cc64930ab2248'
tag = 'company-lms:rate-limit-fix-642a51c8'
services = ['backend', 'frontend', 'queue-long', 'queue-short', 'scheduler', 'websocket']
compose = ['docker', 'compose', '--project-directory', str(root), '-f', str(root / 'compose.yaml')]
new = subprocess.check_output(['docker', 'image', 'inspect', tag, '--format', '{{.Id}}'], text=True).strip()
original = env.read_bytes()
if re.findall(rb'(?m)^LMS_IMAGE=(.+)$', original) != [old.encode()]:
    raise SystemExit('Runtime image changed; refusing deployment')
backup = root / '.env.before-rate-limit-642a51c8'
fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'wb') as f:
    f.write(original)

def replace(data):
    temp = root / '.env.rate-limit-tmp'
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
