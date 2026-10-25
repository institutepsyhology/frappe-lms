"""Deploy only the verified video-choice image, preserving data and rollback.

Run on the existing LMS Docker host, alongside russian-deploy.py. No secrets
are printed. This performs no app upgrade, migration or course content edits.
"""
import datetime
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parent
BASE = Path('/opt/company-lms')
EXPECTED_OLD = 'sha256:35b5b3e30e863b5b4488ee4c60345cebb742cfe4096aa2f582fcd4d62f31229b'
TAG = 'company-lms:video-choice-2.64.0-20261026'


def main():
    if os.geteuid() != 0 or subprocess.check_output(['hostname'], text=True).strip() != 'spb-3-vm-t6fa':
        raise RuntimeError('Unexpected host or user')
    spec = importlib.util.spec_from_file_location('lms_release', ROOT/'russian-deploy.py')
    release = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release)
    new = subprocess.check_output(['docker', 'image', 'inspect', TAG, '--format', '{{.Id}}'], text=True).strip()
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', new) or new == EXPECTED_OLD:
        raise RuntimeError('New image not ready')
    release.OLD, release.NEW = EXPECTED_OLD, new
    if not release.services_healthy(EXPECTED_OLD):
        raise RuntimeError('Current application image differs from reviewed baseline')
    env = BASE/'runtime/.env'
    original = env.read_bytes()
    old_lines = re.findall(rb'^LMS_IMAGE=(.+)$', original, re.M)
    if len(old_lines) != 1 or old_lines[0].strip().decode() != EXPECTED_OLD:
        raise RuntimeError('Runtime image changed since review')
    before = release.snapshot()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = BASE/'backups'/('video-choice-'+stamp)
    backup.mkdir(mode=0o700)
    release.write_new(backup/'runtime.env.before', original)
    release.write_new(backup/'site-counts.before.json', (json.dumps(before)+'\n').encode())
    report = {'previous_image': EXPECTED_OLD, 'image': new, 'backup_directory': str(backup), 'ok': False}
    try:
        updated = re.sub(rb'(?m)^LMS_IMAGE=.+$', ('LMS_IMAGE='+new).encode(), original)
        temp = env.with_name('.env.video-choice-'+stamp)
        release.write_new(temp, updated)
        os.replace(temp, env)
        release.up()
        deadline = time.monotonic()+150
        while True:
            try:
                after = release.snapshot()
                if after != before:
                    raise RuntimeError('Site counts or languages changed')
                checks = [release.verify_http(site) for site in release.SITES]
                if release.services_healthy(new) and all(all(row['checks'].values()) for row in checks):
                    report.update(ok=True, counts_and_language_unchanged=True, sites=checks, application_services_healthy=True)
                    break
            except Exception:
                if time.monotonic() >= deadline:
                    raise
            if time.monotonic() >= deadline:
                raise RuntimeError('Post-deployment verification failed')
            time.sleep(3)
    except Exception as error:
        report['error'] = type(error).__name__
        temp = env.with_name('.env.video-choice-rollback-'+stamp)
        release.write_new(temp, original)
        os.replace(temp, env)
        try:
            release.up()
            deadline = time.monotonic()+150
            while not (release.services_healthy(EXPECTED_OLD) and all(release.ping(site) for site in release.SITES)):
                if time.monotonic() >= deadline:
                    raise RuntimeError('Rollback verification failed')
                time.sleep(3)
            report['rolled_back'] = True
        except Exception:
            report['rolled_back'] = False
    report['completed_at_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    release.write_new(backup/'result.json', (json.dumps(report, ensure_ascii=False, indent=2)+'\n').encode())
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
