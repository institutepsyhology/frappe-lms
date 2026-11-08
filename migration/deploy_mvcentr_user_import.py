"""Install the reviewed importer atop the currently verified LMS image.

Run as root on the LMS host after copying avo_user_import.py beside this file.
The previous runtime environment is retained and restored if health checks fail.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

BASE = Path('/opt/company-lms/runtime')
SOURCE = Path('/tmp/avo_user_import.py')
OLD = 'sha256:798c2cd4ada8b11d175569cefec91510f30810eb343192f6132cba02bb81bb48'
SERVICES = ['backend', 'frontend', 'websocket', 'queue-short', 'queue-long', 'scheduler']
COMPOSE = ['docker', 'compose', '--project-directory', str(BASE), '--profile', 'jobs']


def run(args, timeout=120):
    return subprocess.check_output(args, stderr=subprocess.STDOUT, timeout=timeout, text=True).strip()


def healthy(image):
    ids = run(COMPOSE + ['ps', '-q'] + SERVICES).split()
    if len(ids) != len(SERVICES):
        return False
    states = json.loads(run(['docker', 'inspect'] + ids))
    return all(x['Image'] == image and x['State']['Running'] for x in states)


def main():
    if os.geteuid() != 0 or not SOURCE.is_file() or not healthy(OLD):
        raise RuntimeError('unexpected initial state')
    env = BASE / '.env'
    original = env.read_bytes()
    old_values = re.findall(rb'(?m)^LMS_IMAGE=(.+)$', original)
    if len(old_values) != 1 or old_values[0].decode().strip() != OLD:
        raise RuntimeError('unexpected configured image')
    stamp = str(int(time.time()))
    folder = Path('/opt/company-lms') / ('avo-user-import-' + stamp)
    folder.mkdir(mode=0o700)
    (folder / 'env.before').write_bytes(original)
    os.chmod(folder / 'env.before', 0o600)
    shutil.copyfile(SOURCE, folder / 'avo_user_import.py')
    digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    base_tag = 'company-lms:avo-user-base-' + stamp
    run(['docker', 'tag', OLD, base_tag])
    (folder / 'Dockerfile').write_text('FROM ' + base_tag + '\nCOPY --chown=frappe:frappe avo_user_import.py /home/frappe/frappe-bench/apps/lms/lms/lms/avo_user_import.py\n')
    run(['docker', 'build', '--network=none', '--pull=false', '-t', 'company-lms:avo-user-import-' + stamp, str(folder)], timeout=600)
    image = run(['docker', 'image', 'inspect', 'company-lms:avo-user-import-' + stamp, '--format', '{{.Id}}'])
    test = "import hashlib;print(hashlib.sha256(open('/home/frappe/frappe-bench/apps/lms/lms/lms/avo_user_import.py','rb').read()).hexdigest())"
    if run(['docker', 'run', '--rm', '--network=none', '--entrypoint', 'python3', image, '-c', test]) != digest:
        raise RuntimeError('image source mismatch')
    changed = re.sub(rb'(?m)^LMS_IMAGE=.+$', ('LMS_IMAGE=' + image).encode(), original)
    tmp = BASE / ('.env.avo-user-import-' + stamp)
    tmp.write_bytes(changed)
    os.chmod(tmp, 0o600)
    try:
        os.replace(tmp, env)
        run(COMPOSE + ['up', '-d', '--no-deps'] + SERVICES, timeout=180)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and not healthy(image):
            time.sleep(3)
        if not healthy(image):
            raise RuntimeError('new image unhealthy')
    except Exception:
        tmp.write_bytes(original)
        os.chmod(tmp, 0o600)
        os.replace(tmp, env)
        run(COMPOSE + ['up', '-d', '--no-deps'] + SERVICES, timeout=180)
        raise
    print(json.dumps({'installed': True, 'image': image, 'source_sha256': digest, 'rollback_saved': True}))


if __name__ == '__main__':
    main()

