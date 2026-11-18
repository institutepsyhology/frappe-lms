"""Prepare verified IOMP editor variants while retaining original snapshots."""

import re

from importer import Review
from lms.lms.avo_html_fragment import make_html_block
from lms.lms.avo_transform import plan_import
from normalize_source import clean_table, table_content


EXCLUDED_LESSONS = frozenset({'20', '169', '188', '1405', '1406', '1957', '4396', '4400', '4512', '5296', '5864'})
OMIT_AUDIO_LESSONS = frozenset({'1512', '1792', '1956'})


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
    omit_audio = payload.get('lesson_id') in OMIT_AUDIO_LESSONS

    def walk(parent):
        children = parent.get('children', [])
        kept = []
        for node in children:
            fields = node.get('fields', {})
            name = node.get('name')
            html = fields.get('html')
            if (name == 'button' and html in ('АУДИОЗАПИСЬ', 'АУДИОЗАПИСЬ 1', 'АУДИОЗАПИСЬ 2')
                    and fields.get('linkType') == 'url' and (omit_audio or not fields.get('url')) and not node.get('children')
                    and not any(fields.get(key) for key in ('anchor', 'toAnchor', 'event', 'icon'))
                    and not set(fields) - {'anchor', 'html', 'icon', 'linkType', 'url', 'blank', 'toAnchor', 'event'}):
                continue
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
