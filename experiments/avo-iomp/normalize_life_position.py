"""Restore reviewed media for IOMP lesson 172/2882 using its private archive."""

from copy import deepcopy
import json

from importer import Review
from lms.lms.avo_transform import plan_import
from normalize_reviewed_pairs import _digest


TARGET = '337088bc1c46b9e0d9a2d7a85463695163f1292eb30006e093779d6bfa5a1f3f'
PREPARED = {
    None: '3c871ddaeb00cb7799e856376352517e2c7e1c2e2153c8e6977d2e311d895684',
    'powerpoint': '2af46dbc9937e76f45e1d81aa8f098a7e915e687d34e40514b58dfd772014649',
    'pdf': '7a2aab73ba22a199c9d254830add33a7ab91660efb3f97648a4817501a77740e',
}
DONORS = {
    'powerpoint': (116, 1886, '65b5b161349ef4e76fb7dde3c5bdb7cc3dd4c395788eaa2ef4b4eb605cc92ea3'),
    'pdf': (88, 1029, 'a2f38d661bb282d6f6fcd17c1ab87f3bbbaf99da20788394bd66e8cb16b8e84c'),
}


def _matches(payload, course, lesson):
    return (payload.get('account'), payload.get('source_origin'), payload.get('format'),
            str(payload.get('course_id')), str(payload.get('lesson_id'))) == (
                'iomp', 'https://shop.iomp.ru', 'ape', str(course), str(lesson))


def _read_donor(archive, choice):
    course, lesson, expected = DONORS[choice]
    captures = sorted((archive / f'course-{course}').rglob(f'lesson-{lesson}.json'))
    if not captures:
        raise Review('life_position_donor_missing')
    for capture in captures:
        try:
            donor = json.loads(capture.read_text(encoding='utf-8'))['payload']
            if not _matches(donor, course, lesson) or _digest(donor['ape']) != expected:
                raise Review('life_position_donor_changed')
        except (OSError, ValueError, KeyError, AttributeError, TypeError, RecursionError) as exc:
            raise Review('life_position_donor_unreadable') from exc
    return donor


def _buttons(root, section):
    return [column['children'][0]['fields'] for column in root['children'][section]['children']]


def _compare_materials(target, donor):
    # Compare all four captions and the three known URLs before borrowing the first.
    if ([b['html'] for b in target] != [b['html'] for b in donor]
            or [b['url'] for b in target[1:]] != [b['url'] for b in donor[1:]]):
        raise Review('life_position_materials_mismatch')


def normalize_life_position(payload, archive, presentation=None):
    """Add both verified alternates. With no selection the first button stays in review."""
    if not _matches(payload, 172, 2882):
        return
    if presentation not in PREPARED:
        raise Review('life_position_presentation_unknown')
    digest = _digest(payload['ape'])
    if digest == PREPARED[presentation] or (presentation is None and digest in PREPARED.values()):
        return
    if digest != TARGET and digest not in PREPARED.values():
        raise Review('life_position_source_changed')

    root = deepcopy(payload['ape'])
    target_buttons = _buttons(root, 3)
    source = _read_donor(archive, 'powerpoint')
    source_buttons = _buttons(source['ape'], 4)
    _compare_materials(target_buttons, source_buttons)
    plan = plan_import(source, {})
    pairs = [block['data'] for block in plan['blocks'] if block['type'] == 'videoChoice']
    target_videos = [node['fields'] for node in root['children'] if node['name'] == 'video']
    if (plan['issues'] or [p['youtube'] for p in pairs] != [v['videoSrc'] for v in target_videos]
            or len(pairs) != 2 or not all(p['rutube'] for p in pairs)):
        raise Review('life_position_videos_mismatch')
    for fields, pair in zip(target_videos, pairs):
        fields.update(videoProvider2='rutube', videoSrc2=pair['rutube'])

    if presentation == 'pdf':
        pdf = _read_donor(archive, 'pdf')
        source_buttons = _buttons(pdf['ape'], 3)
        _compare_materials(target_buttons, source_buttons)
        if [n['fields']['videoSrc'] for n in pdf['ape']['children'] if n['name'] == 'video'] != [
                p['youtube'] for p in pairs]:
            raise Review('life_position_videos_mismatch')
    if presentation is not None:
        target_buttons[0]['url'] = source_buttons[0]['url']
    if _digest(root) != PREPARED[presentation]:
        raise Review('life_position_result_changed')
    payload['ape'] = root
