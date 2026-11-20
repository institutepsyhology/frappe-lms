"""Apply reviewed IOMP player choices, retaining the other lesson blocks."""

import hashlib
import json
import re

from importer import Review
from lms.lms.avo_transform import _player_url
from normalize_reviewed_pairs import _digest


ORIGIN = 'https://shop.iomp.ru'
# These hashes include the complete conditioned player nodes in authored order,
# including source URLs and visibility rules, excluding volatile APE node IDs.
TAGGED_PLAYERS = {
    '5934': 'b599b625066e25edf8d44def0acd0a0058823739255eb11c049948de063e9851',
    '5889': '215057d76dd8f901ccbf10d66a3adbd84eca4e22d2d24dce3e83171dff64e3cf',
}
MONEY_PRACTICUM = (193, 3374, 'abb8b429bd155dc8ba83fb68d87851457e88b6c533cbaabf48024d3601afa0f9')
CONCATENATED_YOUTUBE = '9260d8fb50026b1f95824ae1965f93cf3529535b6abde0062b14b69cfaf27b1a'
DONORS = {
    ('219', '3727'): MONEY_PRACTICUM,
    ('335', '6329'): MONEY_PRACTICUM,
    ('249', '4478'): (137, 2149, '6062b9d6f6c563873e718ece9b2dac0f41205cf4ae522908bb1850fac6e6f4a9'),
}


def _videos(node):
    if node.get('name') == 'video':
        yield node
    for child in node.get('children', []):
        yield from _videos(child)


def _read_donor(archive, course, lesson):
    from import_capture import refreshed_lessons

    receipts = sorted((archive / f'course-{course}').glob('*/capture-status.json'))
    try:
        receipt = receipts[-1]
        row = json.loads(receipt.read_text(encoding='utf-8'))
        if (row['account'] != 'iomp' or row['course_id'] != course or row['outline_verified'] is not True
                or lesson not in row['saved'] or lesson not in row['lesson_ids']):
            raise Review('iomp_pair_donor_mismatch')
        refreshed = refreshed_lessons(receipt.parent, str(course), row['lesson_ids'])
        source = refreshed.get(str(lesson), receipt.parent / f'lesson-{lesson}.json')
        p = json.loads(source.read_text(encoding='utf-8'))['payload']
        if (p['account'], p['source_origin'], p['format'], str(p['course_id']), str(p['lesson_id'])) != (
                'iomp', ORIGIN, 'ape', str(course), str(lesson)):
            raise Review('iomp_pair_donor_mismatch')
        return [n['fields'] for n in _videos(p['ape'])]
    except (KeyError, IndexError, TypeError, ValueError, OSError) as exc:
        raise Review('iomp_pair_donor_unavailable') from exc


def normalize_approved_players(payload, archive):
    if (payload.get('account'), payload.get('source_origin'), payload.get('format')) != ('iomp', ORIGIN, 'ape'):
        return
    c, l = str(payload['course_id']), str(payload['lesson_id'])
    page = payload['ape']
    if (c, l) == ('278', '5520'):
        first = next(_videos(page), None)
        if first:
            fields = first['fields']
            url = fields.get('videoSrc', '')
            pair = re.fullmatch(r'(https://youtu\.be/[\w-]{11})https://youtu\.be/[\w-]{11}', url) if isinstance(url, str) else None
            if (pair and hashlib.sha256(url.encode()).hexdigest() == CONCATENATED_YOUTUBE
                    and fields.get('videoProvider') == 'youtube' and fields.get('videoProvider2') == 'rutube'
                    and _player_url(fields.get('videoSrc2'), 'rutube')):
                fields['videoSrc'] = pair[1]
        return
    if c == '321' and l in TAGGED_PLAYERS:
        children = page['children']
        selected = [n for n in children if n['name'] == 'video' and n['fields'].get('visibleConditions')]
        if not selected:
            return
        if _digest({'children': selected}) != TAGGED_PLAYERS[l]:
            raise Review('iomp_conditioned_players_changed')
        omitted = set()
        for node in selected:
            if node['fields']['videoProvider'] == 'html5':
                omitted.add(id(node))
            else:
                del node['fields']['visibleConditions']
        page['children'] = [n for n in children if id(n) not in omitted]
        return
    if (c, l) not in DONORS:
        return
    fields = [n['fields'] for n in _videos(page)]
    if len(fields) != 2 or [f.get('videoProvider') for f in fields] != ['youtube', 'rutube']:
        return
    primary, alternate = fields
    youtube = primary.get('videoSrc')
    if not _player_url(youtube, 'youtube') or alternate.get('videoSrc') not in ('', None, youtube):
        return
    course, lesson, fingerprint = DONORS[c, l]
    donor = _read_donor(archive, course, lesson)
    if (not donor or donor[0].get('videoProvider') != 'youtube' or donor[0].get('videoSrc') != youtube):
        raise Review('iomp_pair_donor_mismatch')
    if len(donor) == 1 and donor[0].get('videoProvider2') == 'rutube':
        url = donor[0].get('videoSrc2')
    elif len(donor) == 2 and donor[1].get('videoProvider') == 'rutube':
        url = donor[1].get('videoSrc')
    else:
        raise Review('iomp_pair_donor_mismatch')
    if not _player_url(url, 'rutube') or hashlib.sha256(url.encode()).hexdigest() != fingerprint:
        raise Review('iomp_pair_donor_changed')
    alternate['videoSrc'] = url
