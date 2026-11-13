"""Fixed overlay/profile guards; fake Git and Docker only, never a real server."""
import importlib.util
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from test_backend_release import directory

HERE=Path(__file__).resolve().parent


def load(name):
    spec=importlib.util.spec_from_file_location('self_linked_test_'+name,HERE/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


profile=load('release_self_linked_images')
context,release=profile.context,profile.release
REVISION='1'*40
CANDIDATE='sha256:'+'2'*64


def git(repo,*args):
    if args[0]=='rev-parse':return REVISION.encode()
    filename=args[1].split(':',1)[1]
    return ((HERE/'create_self_linked_image_context.py').read_bytes().replace(b'\r\n',b'\n')
            if filename==context.GENERATOR else ('committed '+filename+'\n').encode())


class SelfLinkedReleaseTests(unittest.TestCase):
    def package(self,root):
        repo=root/'repo';repo.mkdir()
        with patch.object(context,'git_bytes',side_effect=git):
            report=context.create(root/'context',repo,REVISION)
        return root/'context/source-manifest.json',report

    def test_committed_overlay_has_exact_two_files_and_no_frontend_or_installs(self):
        with directory() as root:
            path,report=self.package(root)
            self.assertEqual(set(report['files']),{'lms/lms/avo_transform.py','lms/lms/test_avo_self_linked_images.py'})
            self.assertEqual(report['baseline_layers'],48)
            self.assertEqual(release.validate_context(path,REVISION),report)
            with tarfile.open(path.parent/'overlay.tar') as archive:
                self.assertEqual(archive.getnames(),list(context.FILES))
                self.assertTrue(all(x.isfile() and x.mtime==0 for x in archive.getmembers()))
            recipe=(path.parent/'Dockerfile').read_text()
            self.assertIn('FROM '+context.BASELINE,recipe)
            self.assertIn('test_avo_self_linked_images',recipe)
            self.assertIn('test_avo_import_unit',recipe)
            self.assertFalse(any(x in recipe for x in ('yarn','npm','pip install','frontend')))

    def test_uncommitted_generator_and_wrong_artifacts_are_rejected(self):
        with directory() as root:
            repo=root/'repo';repo.mkdir()
            with patch.object(context,'git_bytes',side_effect=lambda *a:REVISION.encode() if a[1]=='rev-parse' else b'changed'):
                with self.assertRaisesRegex(ValueError,'generator_not_committed'):context.create(root/'context',repo)
            self.assertFalse((root/'context').exists())
        with directory() as root:
            path,_=self.package(root)
            (path.parent/'overlay.tar').write_bytes(b'foreign overlay')
            with self.assertRaisesRegex(RuntimeError,'artifact_changed'):release.validate_context(path,REVISION)

    def fake(self):
        layers=['layer-'+str(i) for i in range(48)]
        files={name:'a'*64 for name in context.FILES}
        report={'source_revision':REVISION,'files':files,'generator_sha256':'b'*64}
        labels={'org.opencontainers.image.source':context.SOURCE,'org.opencontainers.image.revision':REVISION,
                'ru.mvcentr.baseline':context.BASELINE,'ru.mvcentr.release':context.RELEASE,
                'ru.mvcentr.sources-sha256':context.sources_digest(files),
                'ru.mvcentr.generator-sha256':report['generator_sha256']}
        image={'Id':CANDIDATE,'RootFS':{'Layers':layers+['new-layer']},'Config':{'Labels':labels}}
        shared=SimpleNamespace(SITES=('site-one','site-two','site-three'),prepare=Mock(return_value=0),
                               activate=Mock(return_value=0),validate_backup=Mock())
        def run(args,**kwargs):
            if args==['hostname']:return 'spb-3-vm-t6fa'
            if args[:3]==['docker','image','inspect']:
                return json.dumps([{'Id':context.BASELINE,'RootFS':{'Layers':layers}} if args[3]==context.BASELINE else image])
            if args[:2]==['docker','exec']:return json.dumps([{'site':s,'key_exists':True} for s in shared.SITES])
            if args[:2]==['docker','run']:return json.dumps(files)
            raise AssertionError('unexpected command')
        module=SimpleNamespace(run=Mock(side_effect=run),healthy=Mock(return_value=True),BENCH='/bench',BACKEND='backend')
        return module,shared,layers,report,image

    def test_new_profile_does_not_change_previous_release_profile(self):
        old=load('create_backend_context')
        self.assertEqual(old.BASELINE_LAYERS,47)
        self.assertEqual(release.BASELINE_LAYERS,48)
        self.assertEqual(release.BASELINE,context.BASELINE)
        self.assertNotEqual(old.BASELINE,context.BASELINE)

    def test_valid_candidate_uses_existing_backups_and_cache_only_activation(self):
        module,shared,_,report,_=self.fake()
        with patch.object(release,'deploy_helper',return_value=module), \
                patch.object(release,'validate_context',return_value=report), \
                patch.object(release.os,'geteuid',return_value=0,create=True):
            self.assertEqual(release.prepare(shared),0)
            self.assertEqual(release.activate(CANDIDATE,'/backup',REVISION,'/manifest',shared),0)
        shared.prepare.assert_called_once_with();shared.validate_backup.assert_called_once_with('/backup')
        shared.activate.assert_called_once_with(CANDIDATE,'/backup',REVISION)
        probe=next(call.args[0] for call in module.run.call_args_list if call.args[0][:2]==['docker','run'])
        self.assertIn('--read-only',probe);self.assertIn('--network=none',probe)
        self.assertFalse(any('type=bind' in x or 'type=volume' in x for x in probe))

    def test_foreign_ancestry_label_checksum_or_non48_baseline_stops(self):
        for failure in ('ancestry','label','checksum','baseline'):
            module,shared,layers,report,image=self.fake()
            if failure=='ancestry':image['RootFS']['Layers'][0]='foreign'
            if failure=='label':image['Config']['Labels']['ru.mvcentr.release']='foreign'
            if failure=='baseline':layers.pop()
            if failure=='checksum':
                old=module.run.side_effect
                module.run.side_effect=lambda args,**kw:'{}' if args[:2]==['docker','run'] else old(args,**kw)
            with self.subTest(failure=failure),patch.object(release,'deploy_helper',return_value=module), \
                    patch.object(release,'validate_context',return_value=report), \
                    patch.object(release.os,'geteuid',return_value=0,create=True):
                with self.assertRaises(RuntimeError):release.activate(CANDIDATE,'/backup',REVISION,'/manifest',shared)
            shared.activate.assert_not_called()


if __name__=='__main__':unittest.main()
