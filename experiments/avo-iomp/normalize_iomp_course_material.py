"""Reproduce reviewed IOMP buttons and timing material from local APE copies."""

import hashlib
import re
from html.parser import HTMLParser

from lms.lms.avo_html_fragment import make_html_block
from lms.lms.avo_transform import _player_url
from normalize_accordions import normalize_accordions
from normalize_iomp_material import _digest


EMPTY_THIRD_AUDIO = {('131', '2093'), ('152', '2411')}
SUPERVISION_TIMINGS = {
    ('308', '5783'), ('309', '5828'), ('311', '5795'), ('311', '5796'), ('311', '5797'),
    ('312', '5818'), *(('324', lesson) for lesson in ('6011', '6012', '6013', '6018', '6019', '6020')),
}
SUPERVISION_CAPTIONS = {
    '<strong><span style="font-size: 20px">ПРЕЗЕНТАЦИЯ</span></strong>': 'ПРЕЗЕНТАЦИЯ',
    'МАТЕРИАЛЫ<span style="font-size: 16px"> 2-ГО БЛОКА</span>': 'МАТЕРИАЛЫ 2-ГО БЛОКА',
    'ПРЕЗЕНТАЦИЯ<span style="font-size: 16px"> 1</span>': 'ПРЕЗЕНТАЦИЯ 1',
    'КНИГА<span style="font-size: 16px"> ЖИЛЬБЕРА РЕНО</span>': 'КНИГА ЖИЛЬБЕРА РЕНО',
    'АУДИОЗАПИСЬ <span>2</span>': 'АУДИОЗАПИСЬ 2',
    'АУДИОЗАПИСЬ <span>3</span>': 'АУДИОЗАПИСЬ 3',
    '<span>АУДИОЗАПИСЬ</span>': 'АУДИОЗАПИСЬ',
    'АУДИОЗАПИСЬ<span style="font-size: 16px"> </span>': 'АУДИОЗАПИСЬ',
    'АУДИОЗАПИСЬ<span style="font-size: 16px;"> </span>': 'АУДИОЗАПИСЬ',
    '<span style="font-size: 20px;">АУДИОЗАПИСЬ</span>': 'АУДИОЗАПИСЬ',
    '<span style="font-size: 16px;">МАТЕРИАЛЫ</span>': 'МАТЕРИАЛЫ',
    '<span style="font-size: 16px">МАТЕРИАЛЫ</span>': 'МАТЕРИАЛЫ',
    **{f'АУДИОЗАПИСЬ<span style="font-size: 16px"> {i}</span>': f'АУДИОЗАПИСЬ {i}' for i in (1, 2, 3)},
    **{f'АУДИОЗАПИСЬ<span style="font-size: 16px;"> {i}</span>': f'АУДИОЗАПИСЬ {i}' for i in (1, 2, 3)},
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


class _ClipboardParagraphs(HTMLParser):
    """Locate the office clipboard metadata on real opening tags."""
    tag = re.compile(r'(<p(?: style="[^"<>]*")?) class="docData;DOCY;v5;(\d{1,7});([A-Za-z0-9+/]+={0,2})">')

    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.line_offsets = [0] + [match.end() for match in re.finditer('\n', source)]
        self.edits = []

    def handle_starttag(self, tag, attrs):
        markup = self.get_starttag_text()
        if markup == '<span style="tab-stops:12.322527777777777cm">':
            keep = len('<span')
        else:
            match = self.tag.fullmatch(markup) if tag == 'p' else None
            if not match or len(match[3]) != 4 * ((int(match[2]) + 2) // 3):
                return
            keep = match.end(1)
        line, column = self.getpos()
        start = self.line_offsets[line - 1] + column
        self.edits.append((start + keep, start + len(markup) - 1))


def _remove_clipboard_classes(source):
    parser = _ClipboardParagraphs(source)
    try:
        parser.feed(source)
        parser.close()
    except (ValueError, AssertionError, RecursionError):
        return source
    candidate = source
    for start, end in reversed(parser.edits):
        candidate = candidate[:start] + candidate[end:]
    if candidate != source:
        try:
            make_html_block(candidate)
        except (ValueError, RecursionError):
            return source
    return candidate


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
    label = DECORATED_LABELS.get(identity)
    omit = identity in EMPTY_THIRD_AUDIO
    timing = identity == ('152', '2401')
    timing_panels = []

    def walk(parent):
        children = parent.get('children', [])
        for node in children[:]:
            fields = node.get('fields', {})
            html = fields.get('html')
            if node.get('name') == 'unfolding':
                items = node.get('children', [])
                timing_panels.append(bool(items) and all(
                    item.get('name') == 'unfolding-item' and
                    str(item.get('fields', {}).get('headerHtml', '')).strip().casefold() in
                    ('тайминг', '<strong>тайминг</strong>') for item in items))
            if node.get('name') == 'text' and isinstance(html, str) and ' class="docData;DOCY;v5;' in html:
                fields['html'] = _remove_clipboard_classes(html)
            if (node.get('name') == 'header-simple' and fields.get('level') in ('h1','h2','h3','h4','h5','h6')
                    and isinstance(html, str) and '<br>' in html and re.fullmatch(r'[^<>]+(?:<br>[^<>]+)+', html)
                    and not fields.get('anchor') and not node.get('children') and not set(fields) - {'anchor','level','html'}):
                level = fields.pop('level')
                node['name'] = 'text'
                fields['html'] = f'<{level}>{html}</{level}>'
            if node.get('name') == 'button':
                if omit and html == 'АУДИОЗАПИСЬ 3' and not fields.get('url'):
                    if _digest({key: value for key, value in node.items() if key != 'id'}) == EMPTY_BUTTON_DIGEST:
                        children.remove(node)
                        continue
                if label and html == label[0] and fields.get('linkType') == 'url' and fields.get('url'):
                    fields['html'] = label[1]
                if (isinstance(html, str) and html in SUPERVISION_CAPTIONS
                        and fields.get('linkType') == 'url' and isinstance(fields.get('url'), str)
                        and fields['url'].startswith('https://') and not node.get('children')):
                    fields['html'] = SUPERVISION_CAPTIONS[html]
            elif node.get('name') == 'video':
                for suffix in ('', '2'):
                    provider = fields.get('videoProvider' + suffix)
                    url = fields.get('videoSrc' + suffix)
                    if (provider in ('youtube', 'rutube') and isinstance(url, str) and url != url.strip()
                            and url.count('://') == 1 and not _player_url(url, provider)
                            and _player_url(url.strip(), provider)):
                        fields['videoSrc' + suffix] = url.strip()
            elif node.get('name') == 'text' and isinstance(html, str) and (timing or '<code>' in html):
                digest = hashlib.sha256(html.encode()).hexdigest()
                if timing and digest == TIMING_LIST_DIGEST:
                    candidate = TIMING_ITEM.sub(_preserve_timing_marker, html)
                    make_html_block(candidate)
                    fields['html'] = candidate
                elif digest == PSYCHOSOMATOSIS_TEXT_DIGEST:
                    candidate = html.replace('<code>&laquo;психосоматоз&raquo;</code>', '&laquo;психосоматоз&raquo;')
                    make_html_block(candidate)
                    fields['html'] = candidate
            walk(node)

    walk(payload['ape'])
    if timing_panels and all(timing_panels):
        payload['ape'], _ = normalize_accordions(payload['ape'], make_html_block)
