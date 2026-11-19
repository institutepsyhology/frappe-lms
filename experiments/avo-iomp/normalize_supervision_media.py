"""Fill the approved media slots of IOMP 202/4096 from IOMP 221/4103."""

from copy import deepcopy
import json

from importer import Review
from lms.lms.avo_transform import plan_import
from normalize_life_position import _matches
from normalize_reviewed_pairs import _digest


SOURCE = 'c90fb11c63f8537660b2c59f90cf7eb0bf8e5adae481ffc4932d85dc7a44b66a'
DONOR = '91637080fc844720e454ff503b0e61bfb34ff95747a8373c1248498ab11be3bb'
PREPARED = '89358fd121f90902fc624e8f785786dc675e84c2e854fec8f6f8c8408c1d3f32'


def normalize_supervision_media(payload, archive):
    if not _matches(payload, 202, 4096):
        return
    if payload.get('lesson_title') != 'Супервизия - 22.05.24':
        raise Review('supervision_source_changed')
    fingerprint = _digest(payload['ape'])
    if fingerprint == PREPARED:
        return
    if fingerprint != SOURCE:
        raise Review('supervision_source_changed')

    copies = sorted((archive / 'course-221').rglob('lesson-4103.json'))
    if not copies:
        raise Review('supervision_donor_missing')
    for path in copies:
        try:
            donor = json.loads(path.read_text(encoding='utf-8'))['payload']
            if (not _matches(donor, 221, 4103) or donor.get('lesson_title') != 'Супервизия 12 - 22.05.24'
                    or _digest(donor['ape']) != DONOR):
                raise Review('supervision_donor_changed')
        except (OSError, KeyError, ValueError, TypeError, AttributeError, RecursionError) as exc:
            raise Review('supervision_donor_unreadable') from exc

    plan = plan_import(donor, {})
    choices = [b['data'] for b in plan['blocks'] if b['type'] == 'videoChoice']
    if plan['issues'] or len(choices) != 1 or not choices[0]['youtube'] or not choices[0]['rutube']:
        raise Review('supervision_donor_media_invalid')

    root = deepcopy(payload['ape'])
    video = root['children'][1]['fields']
    video.update(videoSrc=choices[0]['youtube'], videoProvider2='rutube', videoSrc2=choices[0]['rutube'])
    root['children'][2]['fields']['url'] = donor['ape']['children'][2]['fields']['url']
    if _digest(root) != PREPARED:
        raise Review('supervision_result_changed')
    payload['ape'] = root
