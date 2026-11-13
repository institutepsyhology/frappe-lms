"""Use the existing guarded release with the long-image fixed profile.

No build or activation occurs on import. Reuse fresh three-site backups,
cache-only setup, six-service health/ping checks and existing image rollback.
Only the local candidate budget is tightened to the 49-to-50-layer transition.
"""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


context = load('mastervision_long_image_context', 'create_long_image_context.py')
release = load('mastervision_long_image_release', 'release_backend.py')
release.context = context
release.BASELINE, release.BASELINE_LAYERS, release.RELEASE = context.BASELINE, context.BASELINE_LAYERS, context.RELEASE
_existing_verify_candidate = release.verify_candidate


def verify_candidate(module, image, report, baseline_layers):
    layers = release.image_info(module, image).get('RootFS', {}).get('Layers')
    if not isinstance(layers, list) or len(layers) > context.MAX_CANDIDATE_LAYERS:
        raise RuntimeError('candidate_layer_budget_mismatch')
    return _existing_verify_candidate(module, image, report, baseline_layers)


release.verify_candidate = verify_candidate


if __name__ == '__main__': raise SystemExit(release.main())
