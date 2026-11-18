"""Prepare verified IOMP editor variants while retaining original snapshots."""

import hashlib
from html import unescape
import json
import re
from urllib.parse import urlsplit

from importer import Review
from lms.lms.avo_html_fragment import make_html_block
from lms.lms.avo_transform import plan_import
from normalize_source import clean_table, table_content


EXCLUDED_LESSONS = frozenset({'20', '169', '188', '1405', '1406', '1957', '4400', '4512', '5296', '5864'})
REVIEWED_4396_SHA256 = 'c96913515850f0041834d2ec2fafbd862d11038cc09009e661a86f2fd0ccb2fb'


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


def review_4396(payload):
    """Keep the two distinct source videos and both homework text fragments."""
    if (payload.get('course_id'), payload.get('lesson_id')) != ('4', '4396'):
        return
    root = payload['ape']
    source = json.dumps(root, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode()
    if hashlib.sha256(source).hexdigest() != REVIEWED_4396_SHA256:
        return
    first, second, _, homework, instructions = root['children']
    video_ids = [first['fields']['videoSrc'], urlsplit(second['fields']['videoSrc']).path.rsplit('/', 1)[-1]]
    if not all(re.fullmatch(r'[A-Za-z0-9_-]{11}', ident) for ident in video_ids) or len(set(video_ids)) != 2:
        raise Review('reviewed_video_identity_mismatch')
    nodes = []
    for original, ident in zip((first, second), video_ids):
        nodes.append({'id': original['id'], 'name': 'video', 'fields': {
            'anchor': '', 'videoProvider': 'youtube', 'videoSrc': 'https://youtu.be/' + ident,
        }})
    for text in (homework, instructions):
        original_html = text['fields']['html']
        image = re.search(r'<img alt="" style="width: 50px; height: 50px;" src="([^"<>]+)"\s*/>', original_html)
        if not image:
            raise Review('reviewed_image_identity_mismatch')
        clean_html = original_html[:image.start()] + original_html[image.end():]
        make_html_block(clean_html)
        nodes.append({'id': text['id'] + '-icon', 'name': 'image', 'fields': {
            'anchor': '', 'imageSrc': unescape(image.group(1)),
        }})
        nodes.append({**text, 'fields': {**text['fields'], 'html': clean_html}})
    root['children'] = nodes


def normalize_review(payload):
    if (payload.get('account'), payload.get('source_origin'), payload.get('format')) != (
        'iomp', 'https://shop.iomp.ru', 'ape',
    ):
        return
    review_4396(payload)
    root = payload['ape']

    def walk(parent):
        children = parent.get('children', [])
        kept = []
        for node in children:
            fields = node.get('fields', {})
            name = node.get('name')
            html = fields.get('html')
            if (name == 'button' and html in ('АУДИОЗАПИСЬ', 'АУДИОЗАПИСЬ 1', 'АУДИОЗАПИСЬ 2')
                    and fields.get('linkType') == 'url' and not fields.get('url') and not node.get('children')
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
