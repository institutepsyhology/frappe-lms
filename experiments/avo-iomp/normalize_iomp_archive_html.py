"""Import reviewed IOMP timing tables, documents and forms from APE captures."""

import hashlib
import re
from html import escape

from course_audio import DRIVE
from lms.lms.avo_html_fragment import make_html_block
from normalize_accordions import normalize_accordions
from normalize_iomp_course_material import TIMING_ITEM, _preserve_timing_marker
from normalize_iomp_material import _digest, _split_selected, _walk
from normalize_review import clean_timing_table
from normalize_source import table_content


# Snapshots with a single-item OL for each numbered marker. A generic OL may
# contain multiple items and must keep its own counter.
NUMBERED_TIMINGS = {
    '64f198927fa55d4c44b112a1e9ee7cbd81fb8ee2565a84bf45a9409cff0b4c93',
    '91a61b38c466a39abe5cfc23141bef3064a9555ec4406726b563d21b3373db47',
}
GOOGLE_FORM = 'd7b8110f247fda51a8c6afa50bce352aee05bdcc026eae20f9d371f04f3354d0'
DRIVE_DOCUMENTS = {
    '60e69f64d16888d0ffc8316cf28d4864d4514d37f27205f1803f7196ac202322',
    '98e602cc0b2d81f5a0ba94e0cbba7c724015996f866ca1a69ee636777ac53a1e',
    '6751fdcf6a7f46b9fa5bf93e9988c69806a3b7fb635b5cf15922048172b22aeb',
}
TABLES = {
    'c2379580214b2cd30f8704f318e719e9aee0fb2710b56e641d3f01d22f4c7c24',
    'f84907565e10d9d1f1d5778456780df27ac6790d76026f9835f3c19064f092d6',
    '4ae3afca1936c179abc969ad49467614f9f2f18bbaf29b397654057f78c081ed',
    '5b0e5fc87c9cfd50b9dc3982961131843c2c4a48844a7caac3deef9959a8c0f9',
    '09e39978129e81f87ee2952bbe17dce73f776d019f43b17ae85992368995d0bb',
    '15bb1bd2341961006b76e7f163393a7f335b07e7db78e9e58277d6df6fcadb5c',
}
WHITESPACE = {
    '28569832f2695c31ce26494b549abde7d7066185d05b45e4558cf2449570a107',
    'b48cf3e49f3efcf3aa2fe5fc40438692f10bef91bc7da0760b186490978d82c5',
}
CELL_SPACING = {
    '742029ac7c8077474aeaa25a007567b467d53b2f4203fb5008412180fde48418',
    '9e433ea561a688324756c7fb49b6a6eb50be51ec07adc609005334c7e7b9fec2',
}
TIMING_PANELS = {'5885', '5886', '5887', '5888', '5889', '5934'}
TELEGRAM_HELP = {str(lesson) for lesson in range(3840, 3845)}
HELP_TEMPLATE = 'd612de4e18472ddf6d2da75946e867c07a772b3034e6a21ccf0e9cde2b1bde75'
INTRO_HEADINGS = {('321', '5934'), ('294', '5638')}
EMPTY_HEADINGS = {('234', '4117'), ('235', '4219'), ('236', '4283'), ('243', '4381')}
EMPTY_HEADING = 'bf7f19b23a0471039ad79027199b09c4971011a73d77caf420efbe30727e5089'
SAFE_NODE_KEYS = {'name', 'id', 'style', 'children', 'fields'}
# Exact working assets in text blocks whose wrappers were reviewed as static.
INLINE_ILLUSTRATIONS = {
    ('157', '2538'): ('abcde07771d30229a78a66ebb0ea83e25ca294d904925dce833474eefea30c36',
                      '5336a973d4b358a81326129a59b4b21b5e0d06d2969fc930b25f1e094b47b8e6', 2),
    ('333', '6182'): ('b16079b6b598bc32f429a9e9d1c91a59bd03a900db83ec24f366768f16d641e8',
                      '46aa4ff69168b62acda60f1101ff957c67267fa24fc17dbcba2a498f22b4a6ed', 1),
}
# Every archived copy of each passage points to the same Google file.
# Both source URLs returned HTTP 404 when rechecked on 20 November 2026.
MISSING_ILLUSTRATIONS = {
    'c177b84ac918f8634726914ecbe4a8b3a799ce3f7822aee42cb1beedad880c5e',
    '6871427d3d7a7bf33c91eb699b1fe7b08eff32c00b305164b742d261c9818da1',
}
GOOGLE_IMAGE_WRAPPER = re.compile(
    r'<span style="border:none"><span style="display:inline-block"><span style="overflow:hidden">'
    r'<span style="width:\d+px"><span style="height:\d+px"><img\b[^<>]*/>(?:</span>){5}'
)


def _table(source):
    candidate = source.replace('<thead>', '<tbody>').replace('</thead>', '</tbody>')
    candidate = candidate.replace('<th style="', '<td style="font-weight:bold; ').replace('</th>', '</td>')
    candidate = candidate.replace(' scope="col"', '')
    candidate = re.sub(r'(<table style="[^"<>]*)" width="(\d+)"', r'\1; width:\2px"', candidate)
    candidate = re.sub(r'(<col) width="(\d+)"', r'\1 style="width:\2px"', candidate)
    if table_content(candidate) != table_content(source):
        raise ValueError('archive_timing_table_content_changed')
    return candidate


def _material_link(source, label):
    # Called only for individually reviewed static, single-iframe documents.
    url = re.search(r'<iframe src="([^"<>]+)"', source)[1]
    return f'<p><a href="{escape(url, quote=True)}">{label}</a></p>'


def normalize_iomp_archive_html(payload):
    if (payload.get('account'), payload.get('source_origin'), payload.get('format')) != (
        'iomp', 'https://shop.iomp.ru', 'ape',
    ):
        return
    identity = (str(payload.get('course_id')), str(payload.get('lesson_id')))
    if identity in EMPTY_HEADINGS:
        children = payload['ape']['children']
        children[:] = [child for child in children if not (
            child.get('name') == 'header-simple' and
            _digest({key: val for key, val in child.items() if key != 'id'}) == EMPTY_HEADING
        )]
    selected = {}
    for path, node in _walk(payload['ape']):
        fields = node.get('fields', {})
        source = fields.get('html')
        if not isinstance(source, str) or node.get('children') or set(node) - SAFE_NODE_KEYS:
            continue
        if (fields.get('anchor') or fields.get('visibleConditions') or fields.get('displayDelay')
                or set(fields) - {'anchor', 'html', 'level', 'visibleConditions', 'displayDelay'}):
            continue
        kind = node['name']
        if kind == 'header-simple':
            if (identity in INTRO_HEADINGS and fields.get('level') == 'h4'
                    and source == 'Вводное занятие <br>с Жанной Абрамовой'):
                candidate = f'<h4>{source}</h4>'
                make_html_block(candidate)
                node['name'] = 'text'
                fields.pop('level')
                fields['html'] = candidate
            continue
        if kind not in ('text', 'code') or 'level' in fields:
            continue
        if kind == 'text' and identity[0] == '223' and identity[1] in TELEGRAM_HELP:
            token = '{url_personal_secure training=&quot;223&quot; lessonId=&quot;' + identity[1] + '&quot;}'
            template = source.replace(token, '{same lesson}')
            if hashlib.sha256(template.encode()).hexdigest() == HELP_TEMPLATE:
                href = 'https://my-lk.iomp.ru/personal/training/223/view/' + identity[1]
                fields['html'] = source.replace(token, href).replace(
                    '<font color="#1155cc"><b>&nbsp;</b></font>', '<span style="color:#1155cc"><b>&nbsp;</b></span>')
                selected[path] = 1
                continue
        digest = hashlib.sha256(source.encode()).hexdigest()
        illustration = INLINE_ILLUSTRATIONS.get(identity)
        if (kind == 'text' and illustration and digest == illustration[0]
                and _digest(node.get('style')) == illustration[1] and set(fields) == {'anchor', 'html'}):
            selected[path] = illustration[2]
            continue
        if kind == 'code' and digest == GOOGLE_FORM:
            candidate = _material_link(source, 'Открыть форму')
        elif kind != 'text':
            continue
        elif digest in DRIVE_DOCUMENTS:
            candidate = DRIVE.sub(r'\1\2', source)
        elif digest in TABLES:
            candidate = _table(source)
        elif digest in NUMBERED_TIMINGS:
            candidate = TIMING_ITEM.sub(_preserve_timing_marker, source)
        elif digest in WHITESPACE:
            candidate = source.replace('white-space-collapse: preserve', 'white-space: pre-wrap')
        elif digest in MISSING_ILLUSTRATIONS:
            candidate, count = GOOGLE_IMAGE_WRAPPER.subn('', source)
            if count != 1 or table_content(source) != table_content(candidate):
                raise ValueError('archive_illustration_content_changed')
        elif digest in CELL_SPACING:
            candidate = clean_timing_table(source)
        else:
            continue
        make_html_block(candidate)
        fields['html'] = candidate
        node['name'] = 'text'
    if selected:
        payload['ape'] = _split_selected(payload['ape'], selected)
    if ((identity[0] == '321' and identity[1] in TIMING_PANELS)
            or (identity[0] == '223' and identity[1] in TELEGRAM_HELP)):
        payload['ape'], _ = normalize_accordions(payload['ape'], make_html_block)
