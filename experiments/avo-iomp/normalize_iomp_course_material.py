"""Reproduce reviewed IOMP buttons and timing material from local APE copies."""

import hashlib
import re

from lms.lms.avo_html_fragment import make_html_block
from lms.lms.avo_transform import _player_url
from normalize_accordions import normalize_accordions
from normalize_iomp_material import _digest


EMPTY_THIRD_AUDIO = {('131', '2093'), ('152', '2411')}
SUPERVISION_COURSES = {'301', '302', '303', '305', '306', '308', '309', '310', '311'}
SUPERVISION_TIMINGS = {('308', '5783'), ('309', '5828'), ('311', '5795'), ('311', '5796'), ('311', '5797')}
SUPERVISION_CAPTIONS = {
    'АУДИОЗАПИСЬ<span style="font-size: 16px"> </span>': 'АУДИОЗАПИСЬ',
    'АУДИОЗАПИСЬ<span style="font-size: 16px;"> </span>': 'АУДИОЗАПИСЬ',
    '<span style="font-size: 20px;">АУДИОЗАПИСЬ</span>': 'АУДИОЗАПИСЬ',
    '<span style="font-size: 16px;">МАТЕРИАЛЫ</span>': 'МАТЕРИАЛЫ',
    **{f'АУДИОЗАПИСЬ<span style="font-size: 16px"> {i}</span>': f'АУДИОЗАПИСЬ {i}' for i in (1, 2, 3)},
}
EMPTY_BUTTON_DIGEST = '7690d746c001dcd128ba5ea0de3bbd8ae1a6c4a8c6f1c238ec59b7096431be5b'
TIMING_ACCORDIONS = {('131', '2183'), ('152', '2417')}
TIMING_LIST_DIGEST = '91a61b38c466a39abe5cfc23141bef3064a9555ec4406726b563d21b3373db47'
PSYCHOSOMATOSIS_TEXT_DIGEST = '07172274b0af090bafca394a0dca44cec8351d13148a2fd1c4d03cd05a059366'
TIMING_ITEM = re.compile(
    r'(<ol(?: start="([0-9]+)")?>)<li style="list-style-type:decimal-leading-zero" aria-level="([12])">'
)
DECORATED_LABELS = {
    ('131', '2045'): ('АУДИОЗАПИСЬ <span>2</span>', 'АУДИОЗАПИСЬ 2'),
    ('152', '2387'): ('АУДИОЗАПИСЬ <span>2</span>', 'АУДИОЗАПИСЬ 2'),
    ('152', '2385'): ('<span style="font-size: 16px">ОПЛАТИТЬ СУПЕРВИЗИЮ</span>', 'ОПЛАТИТЬ СУПЕРВИЗИЮ'),
}
for lesson in ('2250', '2251', '2252', '2254', '2255', '2256', '2257', '2258', '2259', '2260', '2261', '2283'):
    DECORATED_LABELS['146', lesson] = ('АУДИОЗАПИСЬ<span style="font-size: 16px"> </span>', 'АУДИОЗАПИСЬ')


def _preserve_timing_marker(match):
    # Each reviewed list contains one item. Retain its list/level metadata
    # and print its original two-digit marker with a supported list style.
    opening, start, level = match.groups()
    marker = int(start or 1)
    return f'{opening}<li style="list-style:none" aria-level="{level}">{marker:02d}. '


def normalize_iomp_course_material(payload):
    if (payload.get('account'), payload.get('source_origin'), payload.get('format')) != (
        'iomp', 'https://shop.iomp.ru', 'ape',
    ):
        return
    identity = (payload.get('course_id'), payload.get('lesson_id'))
    if identity in TIMING_ACCORDIONS:
        payload['ape'], _ = normalize_accordions(payload['ape'], make_html_block)
        return
    if identity in SUPERVISION_TIMINGS:
        payload['ape'], _ = normalize_accordions(payload['ape'], make_html_block)
    supervision = identity[0] in SUPERVISION_COURSES
    label = DECORATED_LABELS.get(identity)
    omit = identity in EMPTY_THIRD_AUDIO
    timing = identity == ('152', '2401')
    monospace_term = identity in {('163', '2683'), ('208', '3526')}
    if not (supervision or label or omit or timing or monospace_term):
        return

    def walk(parent):
        children = parent.get('children', [])
        for node in children[:]:
            fields = node.get('fields', {})
            html = fields.get('html')
            if node.get('name') == 'button':
                if omit and html == 'АУДИОЗАПИСЬ 3' and not fields.get('url'):
                    if _digest({key: value for key, value in node.items() if key != 'id'}) == EMPTY_BUTTON_DIGEST:
                        children.remove(node)
                        continue
                if label and html == label[0] and fields.get('linkType') == 'url' and fields.get('url'):
                    fields['html'] = label[1]
                if (supervision and isinstance(html, str) and html in SUPERVISION_CAPTIONS
                        and fields.get('linkType') == 'url' and isinstance(fields.get('url'), str)
                        and fields['url'].startswith('https://') and not node.get('children')):
                    fields['html'] = SUPERVISION_CAPTIONS[html]
            elif node.get('name') == 'video' and identity == ('311', '5795'):
                alternate = fields.get('videoSrc2')
                if (fields.get('videoProvider2') == 'rutube' and isinstance(alternate, str)
                        and alternate != alternate.strip() and _player_url(alternate.strip(), 'rutube')):
                    fields['videoSrc2'] = alternate.strip()
            elif node.get('name') == 'text' and isinstance(html, str) and (timing or monospace_term):
                digest = hashlib.sha256(html.encode()).hexdigest()
                if timing and digest == TIMING_LIST_DIGEST:
                    candidate = TIMING_ITEM.sub(_preserve_timing_marker, html)
                    make_html_block(candidate)
                    fields['html'] = candidate
                elif monospace_term and digest == PSYCHOSOMATOSIS_TEXT_DIGEST:
                    candidate = html.replace('<code>&laquo;психосоматоз&raquo;</code>',
                                             '<span style="font-family:monospace">&laquo;психосоматоз&raquo;</span>')
                    make_html_block(candidate)
                    fields['html'] = candidate
            walk(node)

    walk(payload['ape'])
