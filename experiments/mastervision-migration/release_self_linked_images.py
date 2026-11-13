"""Use the existing guarded release with the self-linked-image fixed profile.

No build or activation occurs on import. CLI requires fresh three-site backups,
the exact healthy 48-layer baseline and committed candidate provenance.
"""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


context = load('mastervision_self_linked_context', 'create_self_linked_image_context.py')
release = load('mastervision_self_linked_release', 'release_backend.py')
release.context = context
release.BASELINE, release.BASELINE_LAYERS, release.RELEASE = context.BASELINE, context.BASELINE_LAYERS, context.RELEASE


if __name__ == '__main__': raise SystemExit(release.main())
