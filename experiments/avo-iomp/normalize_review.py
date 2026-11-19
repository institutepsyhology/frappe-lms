"""Prepare verified IOMP editor variants while retaining original snapshots."""

import hashlib
import re

from importer import Review
from lms.lms.avo_html_fragment import make_html_block
from lms.lms.avo_transform import plan_import
from normalize_source import clean_table, table_content


EXCLUDED_LESSONS = frozenset({
    '345', '2689', '3532',
    # Empty supervision and practice lessons in IOMP courses 202, 237 and 261.
    '4097', '4098', '4099', '4100', '4101', '4448', '4453', '4721', '4722', '4723', '4724',
    '20', '169', '188', '1405', '1406', '1957', '4396', '4400', '4512', '5296', '5864',
    # The owner selected the remaining 36 lessons from course 74.
    '726', '767', '768', '769', '770', '771', '775', '776', '777', '778', '779', '780', '782',
    '783', '784', '785', '786', '787', '788', '789', '790', '791', '792', '793', '794',
    '797', '798', '799', '800', '801', '802', '803', '804', '805', '806', '807', '810',
    '811', '812', '813', '815', '816', '817', '818', '819', '820',
})
OMIT_AUDIO_LESSONS = frozenset({'1512', '1792', '1956'})
OMIT_MATERIAL_BUTTON = {
    ('63', '537'): 'АУДИОЗАПИСЬ',
    ('97', '1277'): 'ПРЕЗЕНТАЦИЯ',
}
# These four posters repeat lesson 1798's YouTube URL in an image-only field.
STALE_POSTER_LESSONS = frozenset({'1798', '1841', '1908', '1910'})
STALE_POSTER_DIGEST = '190ec1840a7e6ed0f9564712987f3ce4ed80720635ba8340e83f1fa4fac17b90'
AUDIO_BUTTON_LABELS = ('АУДИОЗАПИСЬ', 'АУДИОЗАПИСЬ 1', 'АУДИОЗАПИСЬ 2')
MATERIAL_BUTTON_LABELS = (*AUDIO_BUTTON_LABELS, 'ПРЕЗЕНТАЦИЯ')
DRIVE_FILE_LINK = re.compile(r'drive\.google\.com/file/d/[A-Za-z0-9_-]+/view(?:\?usp=[A-Za-z0-9_-]+)?')


def clean_timing_table(source):
    """Remove clipboard layout metadata and keep the ordered cells and links."""
    candidate = re.sub(r'''(<(?:td|th)\b[^<>]*?)\s+valign\s*=\s*(["'])(?:top|middle|bottom|baseline)\2''',
                       r'\1', source, flags=re.I)
    candidate = re.sub(r'''<a\s+id\s*=\s*(["'])([A-Za-z0-9_.-]{1,100})\1\s*>([^<>]*)</a>''',
                       r'<span id="\2">\3</span>', candidate, flags=re.I)
    try:
        make_html_block(candidate)
    except (ValueError, UnicodeError, RecursionError):
        candidate, _ = clean_table(candidate)
    if table_content(source) != table_content(candidate):
        raise Review('static_table_content_changed')
    return candidate


def normalize_review(payload):
    if (payload.get('account'), payload.get('source_origin'), payload.get('format')) != (
        'iomp', 'https://shop.iomp.ru', 'ape',
    ):
        return
    root = payload['ape']
    course_id, lesson_id = payload.get('course_id'), payload.get('lesson_id')
    omit_audio = lesson_id in OMIT_AUDIO_LESSONS
    omit_button = OMIT_MATERIAL_BUTTON.get((course_id, lesson_id))

    def walk(parent):
        children = parent.get('children', [])
        kept = []
        for node in children:
            fields = node.get('fields', {})
            name = node.get('name')
            html = fields.get('html')
            if name == 'video' and course_id == '38' and lesson_id in STALE_POSTER_LESSONS:
                poster = fields.get('posterSrc')
                if (isinstance(poster, str) and poster.isascii()
                        and hashlib.sha256(poster.encode()).hexdigest() == STALE_POSTER_DIGEST):
                    fields.pop('posterSrc')
            if (name == 'button' and html in MATERIAL_BUTTON_LABELS and fields.get('linkType') == 'url'
                    and not node.get('children')
                    and not any(fields.get(key) for key in ('anchor', 'toAnchor', 'event', 'icon'))
                    and not set(fields) - {'anchor', 'html', 'icon', 'linkType', 'url', 'blank', 'toAnchor', 'event'}):
                url = fields.get('url')
                if url in (None, '') or html == omit_button or (omit_audio and html in AUDIO_BUTTON_LABELS):
                    continue
                if isinstance(url, str) and DRIVE_FILE_LINK.fullmatch(url):
                    fields['url'] = 'https://' + url
            if (name in ('header', 'text') and isinstance(html, str) and not node.get('children')
                    and not fields.get('anchor') and not set(fields) - {'anchor', 'html', 'format'}):
                if name == 'header':
                    probe = {**payload, 'ape': {**root, 'children': [node]}}
                    if 'unsupported_header' in plan_import(probe, {})['issues']:
                        try:
                            make_html_block(html)
                        except (ValueError, UnicodeError, RecursionError):
                            pass
                        else:
                            node['name'] = 'text'
                            fields.pop('format', None)
                if name == 'text' and '<table' in html.lower():
                    try:
                        make_html_block(html)
                    except (ValueError, UnicodeError, RecursionError):
                        try:
                            fields['html'] = clean_timing_table(html)
                        except (Review, ValueError, UnicodeError, RecursionError):
                            pass
            walk(node)
            kept.append(node)
        if 'children' in parent:
            parent['children'] = kept

    walk(root)
