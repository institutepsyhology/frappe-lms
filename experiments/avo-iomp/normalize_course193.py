"""Reproduce the reviewed IOMP course 193 material in supported lesson blocks."""

import hashlib
import re

from lms.lms.avo_html_fragment import make_html_block
from normalize_source import table_content


LABEL_LESSONS = {'3279', '3265', '3418', '3266', '3275', '3267', '3274', '3269', '3585'}
LABEL_SPAN = re.compile(
    r'([^<>]*)<span(?: style="font-size: 16px(?:; line-height: 1\.4)?")?>([^<>]+)</span>([^<>]*)'
)
TIMING_DIGESTS = {
    '3272': '4ae3afca1936c179abc969ad49467614f9f2f18bbaf29b397654057f78c081ed',
    '3266': 'c2379580214b2cd30f8704f318e719e9aee0fb2710b56e641d3f01d22f4c7c24',
    '3275': '5b0e5fc87c9cfd50b9dc3982961131843c2c4a48844a7caac3deef9959a8c0f9',
    '3268': 'c177b84ac918f8634726914ecbe4a8b3a799ce3f7822aee42cb1beedad880c5e',
    '3274': '28569832f2695c31ce26494b549abde7d7066185d05b45e4558cf2449570a107',
    '3495': '09e39978129e81f87ee2952bbe17dce73f776d019f43b17ae85992368995d0bb',
    '3271': 'f84907565e10d9d1f1d5778456780df27ac6790d76026f9835f3c19064f092d6',
    '3665': '15bb1bd2341961006b76e7f163393a7f335b07e7db78e9e58277d6df6fcadb5c',
}
TABLE_HEADER = re.compile(r'<th style="([^"<>]+)" scope="col">')
UNAVAILABLE_IMAGE = re.compile(
    r'<span style="display:inline-block"><span style="overflow:hidden"><span style="width:602px">'
    r'<span style="height:300px"><img width="602" height="300" '
    r'src="https://lh7-us\.googleusercontent\.com/[^"<>]+" /></span></span></span></span>'
)


def _timing_html(source, lesson):
    # Frappe admits table rows and cells but not the thead/th elements.
    # Keep every row, cell, list marker, link and style of its contents.
    candidate = source.replace('<thead>', '<tbody>').replace('</thead>', '</tbody>')
    candidate = TABLE_HEADER.sub(r'<td style="font-weight:700; text-align:center; \1">', candidate)
    candidate = candidate.replace('</th>', '</td>')
    candidate = candidate.replace('white-space-collapse: preserve;', 'white-space:pre-wrap;')
    if lesson == '3268':
        # The owner approved omitting this Google image (404). Its timecode
        # shares the paragraph but is outside these four image layout spans.
        candidate, count = UNAVAILABLE_IMAGE.subn('', candidate)
        if count != 1:
            raise ValueError('iomp_timing_image_changed')
    make_html_block(candidate)
    if table_content(source) != table_content(candidate):
        raise ValueError('iomp_timing_content_changed')
    return candidate


def normalize_course193(payload):
    if (payload.get('account'), payload.get('source_origin'), payload.get('format'), payload.get('course_id')) != (
        'iomp', 'https://shop.iomp.ru', 'ape', '193',
    ):
        return
    lesson = payload.get('lesson_id')
    digest = TIMING_DIGESTS.get(lesson)
    if lesson not in LABEL_LESSONS and not digest:
        return
    pending = [payload['ape']]
    while pending:
        node = pending.pop()
        pending.extend(node.get('children', []))
        fields = node.get('fields', {})
        markup = fields.get('html')
        if not isinstance(markup, str) or node.get('children'):
            continue
        if (node.get('name') == 'button' and lesson in LABEL_LESSONS
                and fields.get('linkType') == 'url' and fields.get('url')):
            label = LABEL_SPAN.fullmatch(markup)
            if label:
                fields['html'] = ''.join(label.groups())
        elif node.get('name') == 'text' and digest and hashlib.sha256(markup.encode()).hexdigest() == digest:
            fields['html'] = _timing_html(markup, lesson)
