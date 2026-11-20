"""Keep both source players when inline formatting divides the main label."""

import hashlib

from importer import Review
from lms.lms.avo_transform import _legacy_player_pairs
from normalize_iomp_approved_players import ORIGIN


LESSONS = {('235', '4472'), ('236', '4473'), ('243', '4383')}
SPLIT_LABEL = ('<p style="text-align: center;"><span style="color:#ffffff;"><strong>ОСНОВН</strong>'
               '</span><strong style="color: rgb(255, 255, 255);">ОЙ ПЛЕЕР</strong></p>')
POSTER = '711d7885b925ffbe17eafdc07e99446cf31825fcdbde0576be31df174f08e527'


def _retain_shared_poster(payload):
    """Render the shared cover once, directly above its original player pair."""
    root = payload['ape']
    matched, _, unmatched = _legacy_player_pairs(root)
    if len(matched) != 1 or unmatched:
        raise Review('iomp_poster_pair_changed')
    nodes = [root]
    main = None
    while nodes:
        node = nodes.pop()
        children = node.get('children', [])
        nodes.extend(children)
        if len(children) == 2 and id(children[1]) in matched:
            main = node
    if main is None:
        # After conversion the main column starts with the retained image.
        return
    video = main['children'][1]
    primary, alternate = video['fields'], matched[id(video)]
    poster = primary.get('posterSrc')
    if not poster and not alternate.get('posterSrc'):
        return
    if (not isinstance(poster, str) or alternate.get('posterSrc') != poster
            or hashlib.sha256(poster.encode()).hexdigest() != POSTER):
        raise Review('iomp_pair_poster_changed')
    main['children'].insert(0, {'id': 'iomp-223-pair-poster', 'name': 'image',
                                'fields': {'imageSrc': poster}, 'children': []})
    primary.pop('posterSrc')
    alternate.pop('posterSrc')


def normalize_split_player_label(payload):
    if (payload.get('account'), payload.get('source_origin'), payload.get('format')) != ('iomp', ORIGIN, 'ape'):
        return
    course, lesson = str(payload.get('course_id')), str(payload.get('lesson_id'))
    if course == '223' and lesson in {'3840', '3841', '3842', '3843', '3844'}:
        _retain_shared_poster(payload)
        return
    if (course, lesson) not in LESSONS:
        return
    pending = [payload['ape']]
    while pending:
        node = pending.pop()
        if node['name'] == 'text' and node.get('fields', {}).get('html') == SPLIT_LABEL:
            node['fields']['html'] = '<p>ОСНОВНОЙ ПЛЕЕР</p>'
        pending.extend(node.get('children', []))
