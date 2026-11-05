#!/usr/bin/env python3
"""Re-verify and switch to the pinned compacted image, with rollback."""
import datetime
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
BASE = Path('/opt/company-lms')
SOURCE = 'sha256:3f17259b3d8233c36db2d4abf812289b61c76cc5a139b96b10c6c24cf234ccae'
CANDIDATE = 'sha256:b90574d3160c04f5d1597a85a30f23cbdeee017607d89729333237d3e6d13486'
SITES = ('my-lk.mastervision.su', 'my-lk.iomp.ru', 'my-lk.mv-centr.ru')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    if len(sys.argv) != 2 or not re.fullmatch(r'[0-9a-f]{40}', sys.argv[1]):
        raise RuntimeError('expected_full_reviewed_commit')
    release = load('previous_release', ROOT / 'experiments/avo-html-fragment/deploy.py')
    helper = load('release_helpers', ROOT / 'russian-deploy.py')
    if os.geteuid() != 0 or release.command(['hostname']) != 'spb-3-vm-t6fa':
        raise RuntimeError('unexpected_host')
    if not helper.services_healthy(SOURCE):
        raise RuntimeError('unexpected_runtime_image')
    env = BASE / 'runtime/.env'
    original = env.read_bytes()
    lines = re.findall(rb'^LMS_IMAGE=(.+)$', original, re.M)
    if len(lines) != 1 or lines[0].strip().decode() != SOURCE:
        raise RuntimeError('unexpected_runtime_configuration')
    before = helper.snapshot()
    release_before = release.release_states()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup_dir = BASE / 'backups' / ('image-compaction-' + stamp)
    backup_dir.mkdir(mode=0o700)
    helper.write_new(backup_dir / 'runtime.env.before', original)
    helper.write_new(backup_dir / 'site-counts.before.json', (json.dumps(before) + '\n').encode())
    report = {'source_commit': sys.argv[1], 'previous_image': SOURCE,
              'candidate_image': CANDIDATE, 'backup_directory': str(backup_dir), 'ok': False}
    switched = False
    try:
        # The exact comparison runs immediately before the switch; its IDs must
        # match the live source and candidate, so stale evidence cannot pass.
        result = subprocess.run([sys.executable, str(ROOT / 'experiments/image-compaction/verify_candidate.py')],
                                capture_output=True, text=True, timeout=2400, check=True)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        proof = rows[-1]
        if (proof.get('ok') is not True or proof.get('source_image') != SOURCE
                or proof.get('candidate_image') != CANDIDATE or proof.get('layers') != 1
                or proof.get('configuration_identical') is not True
                or proof.get('filesystem_identical') is not True
                or proof.get('application_imports_ok') is not True
                or proof.get('filesystem_entries_compared', 0) < 100000):
            raise RuntimeError('candidate_proof_invalid')
        report['verification'] = proof
        if not helper.services_healthy(SOURCE) or env.read_bytes() != original:
            raise RuntimeError('runtime_changed_during_verification')
        backups = []
        for site in SITES:
            out = release.command(['docker','exec','-i','-u','frappe','-w','/home/frappe/frappe-bench/sites',
                release.BACKEND,'/home/frappe/frappe-bench/env/bin/python','-c',release.BACKUP,site,stamp],timeout=300)
            records = [line.removeprefix('SAFE_BACKUP:') for line in out.splitlines() if line.startswith('SAFE_BACKUP:')]
            if len(records) != 1:
                raise RuntimeError('backup_not_confirmed')
            backups.append(json.loads(records[0]))
        report['database_backups'] = backups
        temp = env.with_name('.env.image-compaction-' + stamp)
        helper.write_new(temp, re.sub(rb'(?m)^LMS_IMAGE=.+$', ('LMS_IMAGE=' + CANDIDATE).encode(), original))
        os.replace(temp, env)
        switched = True
        helper.up()
        deadline = time.monotonic() + 150
        while not helper.services_healthy(CANDIDATE) or not all(helper.ping(site) for site in SITES):
            if time.monotonic() >= deadline:
                raise RuntimeError('new_image_health_failed')
            time.sleep(3)
        if helper.snapshot() != before or release.release_states() != release_before:
            raise RuntimeError('site_state_changed')
        report.update(ok=True, counts_and_languages_unchanged=True,
                      release_switches_unchanged=True, application_services_healthy=True)
    except Exception as error:
        report['error'] = type(error).__name__
        if isinstance(error, RuntimeError):
            report['detail'] = str(error)
        if switched:
            try:
                temp = env.with_name('.env.image-compaction-rollback-' + stamp)
                helper.write_new(temp, original)
                os.replace(temp, env)
                helper.up()
                deadline = time.monotonic() + 150
                while not helper.services_healthy(SOURCE) or not all(helper.ping(site) for site in SITES):
                    if time.monotonic() >= deadline:
                        raise RuntimeError('rollback_health_failed')
                    time.sleep(3)
                report['rolled_back'] = True
            except Exception:
                report['rolled_back'] = False
    report['completed_at_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    helper.write_new(backup_dir / 'result.json', (json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode())
    print(json.dumps(report,ensure_ascii=False))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
