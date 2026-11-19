"""Prepare the five native video choices of IOMP 146/2249 from private captures."""

import copy
import hashlib
from html import unescape
import json
import re

from importer import Review
from lms.lms.avo_transform import _player_url


# Fingerprints include all authored text, styles, player URLs and settings,
# excluding only the generated editor-node IDs. Media links stay in the archive.
SOURCE = '3cf4b558e57874a10dded618fa8a32388a6a1b0a6491978b2d7403e3a3865b9d'
PREPARED = 'c47f825309a2833637b230a6c9e26d14182506f54fbd21e4e65daff872121893'
DONORS = (
    (163, 2667, '0e9b01e2501d50d4858d1a41b188a5f0721f2ba6a34779699b199fe0438581fc', (5, 8, 11)),
    (211, 3590, 'b214f92d463e8176b37d54e354793b54fc4477dd5a5e0e7a5231521574f9c659', (5, 8, 11, 14)),
)


def _authored(node):
    result = {key: value for key, value in node.items() if key != 'id'}
    if 'children' in node:
        result['children'] = [_authored(child) for child in node['children']]
    return result


def _digest(root):
    encoded = json.dumps(_authored(root), ensure_ascii=True, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('ascii')
    return hashlib.sha256(encoded).hexdigest()


def _heading(node):
    return unescape(re.sub(r'<[^>]+>', '', node['fields']['html'])).strip()


def _donor_pairs(archive):
    pairs = {}
    for course, lesson, digest, indices in DONORS:
        directory = archive / f'course-{course}'
        files = list(directory.rglob(f'lesson-{lesson}.json'))
        if not files:
            raise Review('reviewed_pair_donor_missing')
        for path in files:
            try:
                donor = json.loads(path.read_text(encoding='utf-8'))['payload']
                if (donor.get('account'), donor.get('source_origin'), donor.get('format'),
                        str(donor.get('course_id')), str(donor.get('lesson_id'))) != (
                        'iomp', 'https://shop.iomp.ru', 'ape', str(course), str(lesson)):
                    raise Review('reviewed_pair_donor_changed')
                root = donor['ape']
                if _digest(root) != digest:
                    raise Review('reviewed_pair_donor_changed')
                children = root['children']
                for index in indices:
                    fields = children[index]['fields']
                    primary, alt = fields['videoSrc'], fields['videoSrc2']
                    if ((fields.get('videoProvider'), fields.get('videoProvider2')) != ('youtube', 'rutube')
                            or not _player_url(primary, 'youtube') or not _player_url(alt, 'rutube')):
                        raise Review('reviewed_pair_media_invalid')
                    candidate = (_heading(children[index - 1]), alt)
                    if pairs.setdefault(primary, candidate) != candidate:
                        raise Review('reviewed_pair_donor_conflict')
            except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError) as exc:
                raise Review('reviewed_pair_donor_unreadable') from exc
    return pairs


def normalize_reviewed_pairs(payload, archive):
    """Mutate this lesson only, after verifying both donors and the complete result."""
    if (payload.get('account'), payload.get('source_origin'), payload.get('format'),
            str(payload.get('course_id')), str(payload.get('lesson_id'))) != (
            'iomp', 'https://shop.iomp.ru', 'ape', '146', '2249'):
        return
    digest = _digest(payload['ape'])
    if digest == PREPARED:
        return
    if digest != SOURCE:
        raise Review('reviewed_pair_source_changed')
    pairs = _donor_pairs(archive)
    root = copy.deepcopy(payload['ape'])
    children = root['children']
    for index in (3, 6, 9, 12):
        primary, alternate = children[index]['children']
        youtube = primary['children'][1]['fields']['videoSrc']
        found = pairs.get(youtube)
        if not found or _heading(children[index - 1]) != found[0]:
            raise Review('reviewed_pair_context_mismatch')
        alternate['children'][1]['fields']['videoSrc'] = found[1]

    # The first YouTube has no confirmed alternate. Leave its video intact,
    # omitting the empty alternate and the now redundant player selector labels.
    single = children[0]['children'][0]
    single['children'] = single['children'][1:]
    children[0]['children'] = [single]
    if _digest(root) != PREPARED:
        raise Review('reviewed_pair_result_changed')
    payload['ape'] = root
