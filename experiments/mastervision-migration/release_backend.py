"""Guarded Python-only release; run on the LMS host with migration writers stopped.

Reuses fresh three-site backups, cache-only setup and six-service image rollback.
Does not build, migrate schema, assign roles, publish lessons or run import jobs.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import tarfile

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


context = load('mastervision_backend_context', HERE / 'create_backend_context.py')
BASELINE, BASELINE_LAYERS, RELEASE = context.BASELINE, context.BASELINE_LAYERS, context.RELEASE


def shared_release():
    module = load('mastervision_shared_release', HERE.parent / 'private-course-access/release.py')
    module.BASELINE, module.RELEASE = BASELINE, RELEASE
    return module


def deploy_helper(shared):
    return shared.load('mastervision_backend_guard',
                       HERE.parent / 'avo-credential-profiles-interface/deploy.py')


def image_info(module, image):
    rows = json.loads(module.run(['docker', 'image', 'inspect', image]))
    if not isinstance(rows, list) or len(rows) != 1 or rows[0].get('Id') != image:
        raise RuntimeError('image_identity_mismatch')
    return rows[0]


def guard_runtime(module):
    if getattr(os, 'geteuid', lambda: -1)() != 0 or module.run(['hostname']) != 'spb-3-vm-t6fa':
        raise RuntimeError('unexpected_host_or_user')
    if not module.healthy(BASELINE):
        raise RuntimeError('active_image_changed')
    layers = image_info(module, BASELINE).get('RootFS', {}).get('Layers', [])
    if len(layers) != BASELINE_LAYERS:
        raise RuntimeError('baseline_layer_count_mismatch')
    return layers


def existing_keys(module, sites):
    # init reads existing configuration; no connection, key generator or commit.
    code = '''import frappe,json
out=[]
for site in %r:
 frappe.init(site=site)
 try:out.append({'site':site,'key_exists':bool(frappe.conf.get('encryption_key'))})
 finally:frappe.destroy()
print(json.dumps(out))
''' % (tuple(sites),)
    rows = json.loads(module.run(['docker', 'exec', '-u', 'frappe', '-w', module.BENCH + '/sites',
                                  module.BACKEND, module.BENCH + '/env/bin/python', '-B', '-c', code]))
    if (not isinstance(rows, list) or len(rows) != len(sites)
            or {row.get('site') for row in rows} != set(sites)
            or not all(row.get('key_exists') is True for row in rows)):
        raise RuntimeError('existing_encryption_key_required')


def validate_context(path, revision):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64_000:
        raise RuntimeError('invalid_context_manifest')
    report = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(report, dict) or report.get('release') != RELEASE or report.get('source') != context.SOURCE
            or report.get('source_revision') != revision or report.get('baseline_image') != BASELINE
            or report.get('baseline_layers') != BASELINE_LAYERS):
        raise RuntimeError('context_provenance_mismatch')
    files = report.get('files', {})
    if (not isinstance(files, dict) or set(files) != set(context.FILES)
            or not all(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) for value in files.values())):
        raise RuntimeError('context_source_allowlist_mismatch')
    generator_hash = context.sha((HERE / Path(context.GENERATOR).name).read_bytes().replace(b'\r\n', b'\n'))
    if report.get('generator_sha256') != generator_hash:
        raise RuntimeError('context_generator_mismatch')
    recipe, overlay = path.parent / 'Dockerfile', path.parent / 'overlay.tar'
    for item, maximum in ((recipe, 20_000), (overlay, len(context.FILES) * 2_000_000 + 100_000)):
        if item.is_symlink() or not item.is_file() or not 0 < item.stat().st_size <= maximum:
            raise RuntimeError('invalid_context_artifact')
    if (recipe.read_bytes() != context.dockerfile(revision, files, generator_hash)
            or context.sha(recipe.read_bytes()) != report.get('dockerfile_sha256')
            or context.sha(overlay.read_bytes()) != report.get('overlay_sha256')):
        raise RuntimeError('context_artifact_changed')
    with tarfile.open(overlay) as archive:
        members = archive.getmembers()
        if [member.name for member in members] != list(context.FILES):
            raise RuntimeError('overlay_source_allowlist_mismatch')
        for member in members:
            if not member.isfile() or not 0 < member.size <= 2_000_000:
                raise RuntimeError('invalid_overlay_member')
            if context.sha(archive.extractfile(member).read()) != files[member.name]:
                raise RuntimeError('overlay_source_checksum_mismatch')
    return report


def verify_candidate(module, image, report, baseline_layers):
    candidate = image_info(module, image)
    layers = candidate.get('RootFS', {}).get('Layers', [])
    if (layers[:BASELINE_LAYERS] != baseline_layers
            or not BASELINE_LAYERS < len(layers) <= BASELINE_LAYERS + 2):
        raise RuntimeError('candidate_layer_ancestry_mismatch')
    labels = candidate.get('Config', {}).get('Labels') or {}
    expected = {'org.opencontainers.image.source': context.SOURCE,
                'org.opencontainers.image.revision': report['source_revision'],
                'ru.mvcentr.baseline': BASELINE, 'ru.mvcentr.release': RELEASE,
                'ru.mvcentr.sources-sha256': context.sources_digest(report['files']),
                'ru.mvcentr.generator-sha256': report['generator_sha256']}
    if any(labels.get(key) != value for key, value in expected.items()):
        raise RuntimeError('candidate_provenance_mismatch')
    code = ("import hashlib,json,pathlib;p=pathlib.Path('/home/frappe/frappe-bench/apps/lms');"
            "print(json.dumps({n:hashlib.sha256((p/n).read_bytes()).hexdigest() for n in "
            + repr(tuple(context.FILES)) + '}))')
    # No host bind mounts, production volumes, database or external networking.
    args = ['docker', 'run', '--rm', '--network=none', '--read-only', '--memory=256m', '--pids-limit=64']
    for directory in ('/tmp', module.BENCH + '/sites', module.BENCH + '/logs'):
        args += ['--tmpfs', directory + ':rw,nosuid,nodev,size=8m']
    args += ['--entrypoint', module.BENCH + '/env/bin/python', image, '-B', '-c', code]
    if json.loads(module.run(args, timeout=90)) != report['files']:
        raise RuntimeError('candidate_source_checksum_mismatch')


def prepare(shared=None):
    shared = shared or shared_release()
    module = deploy_helper(shared)
    guard_runtime(module)
    existing_keys(module, shared.SITES)
    return shared.prepare()


def activate(image, backup_manifest, source_revision, source_manifest, shared=None):
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image) or image == BASELINE:
        raise RuntimeError('candidate_image_invalid')
    if not re.fullmatch(r'[0-9a-f]{40}', source_revision):
        raise RuntimeError('source_revision_invalid')
    report = validate_context(source_manifest, source_revision)
    shared = shared or shared_release()
    module = deploy_helper(shared)
    baseline_layers = guard_runtime(module)
    shared.validate_backup(backup_manifest)
    verify_candidate(module, image, report, baseline_layers)
    # Its activation overrides setup_sites with cache clearing only and restores
    # the previous .env/image if a health, ping or site-count check fails.
    return shared.activate(image, backup_manifest, source_revision)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('prepare')
    command = commands.add_parser('activate')
    command.add_argument('image')
    command.add_argument('--backup-manifest', required=True)
    command.add_argument('--source-revision', required=True)
    command.add_argument('--source-manifest', required=True)
    args = parser.parse_args()
    shared = shared_release()
    if (getattr(os, 'geteuid', lambda: -1)() != 0
            or shared.subprocess.check_output(['hostname'], text=True).strip() != 'spb-3-vm-t6fa'):
        raise RuntimeError('unexpected_host_or_user')
    with shared.release_lock():
        return (prepare(shared) if args.command == 'prepare' else
                activate(args.image, args.backup_manifest, args.source_revision, args.source_manifest, shared))


if __name__ == '__main__':
    raise SystemExit(main())
