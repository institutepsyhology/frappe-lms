"""Prepare reviewed IOMP material and preserve static text around inline images."""

import hashlib
import json
import re
from urllib.parse import urlsplit

from avatar_placeholders import _decoded_safe_path
from importer import Review
from lms.lms.avo_html_fragment import make_html_block
from lms.lms.avo_transform import plan_import
from normalize_inline_images import Document, normalize_inline_images


# Reviewed digests cover styles, field values and any children. AVO may assign a
# fresh top-level editor UUID on recapture without changing this material.
REVIEWED_NODES = {
    ('44', '243'): 'c2f8e67bea7ff3d4fd6e67bceda13f0fe85f505c954dc4c31413203895230d1e',
    ('60', '342'): '98513e207d6255da09809db26b822d6890ffcb26260befbf37cb10485d54f6b1',
    ('89', '1065'): '98513e207d6255da09809db26b822d6890ffcb26260befbf37cb10485d54f6b1',
    ('52', '336'): '8114c1a6cf7ba2e2398c7d119896b4d9a0b012c4d25df9a3a9477a61cb8b792d',
    ('65', '481'): 'e367cffeea36098c8ceae4ea664ed4b915a251ab12e6e47bff50147dedf9d6f6',
}
IMAGE_URL_DIGEST = 'e8d170a9df9a146462ed0017cf561efc8d75cbf4c918ec3f3788f56dc40bf7fc'
# This is the AVO text block's reviewed responsive formatting, without a
# visibility condition, background image, caption or authored widget.
ORDINARY_TEXT_STYLE = '46aa4ff69168b62acda60f1101ff957c67267fa24fc17dbcba2a498f22b4a6ed'
IMAGE_TAG = re.compile(r'<\s*img\b', re.I)
IMAGE_PARAGRAPH = re.compile(r'<p>\s*(?:<strong>\s*)?<img\b[^<>]*>(?:\s*</strong>)?\s*</p>', re.I)
PROSE_TAGS = frozenset('p br strong b i em u a ul ol li img'.split())


def _digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def _walk(node, path=()):
    yield path, node
    for index, child in enumerate(node.get('children', [])):
        yield from _walk(child, (*path, index))


def _ordinary_image(url):
    address = urlsplit(url)
    return (address.scheme == 'https' and '?' not in url and '#' not in url
            and (address.netloc == 'shop.iomp.ru' or re.fullmatch(r'f[0-9]+\.autoweboffice\.(?:ru|com)', address.netloc))
            and _decoded_safe_path(address.path) and re.search(r'\.(?:jpe?g|png|webp)$', address.path, re.I))


def _ordinary_pair(node, html):
    fields = node.get('fields', {})
    if (node.get('name') != 'text' or node.get('children') or set(fields) - {'anchor', 'html'}
            or fields.get('anchor') or set(node) - {'id', 'name', 'fields', 'style', 'children'}
            or (node.get('style') and _digest(node['style']) != ORDINARY_TEXT_STYLE)
            or len(html) > 200000 or len(IMAGE_PARAGRAPH.findall(html)) != 2
            or set(re.findall(r'</?([a-zA-Z][\w:-]*)\b', html.lower())) - PROSE_TAGS):
        return False
    try:
        images = Document(html).images
        return len(images) == 2 and all(
            not set(image.attrs) - {'src', 'alt', 'width', 'height', 'style'}
            and not re.search(r'(?:float|margin)\s*:', image.attrs.get('style', ''), re.I)
            and _ordinary_image(image.attrs['src']) for image in images
        )
    except (Review, ValueError, UnicodeError, RecursionError):
        return False


def _split_selected(root, expected_images):
    updated, changes = normalize_inline_images(root, make_html_block, selected_paths=expected_images)
    if {tuple(change['path']): change['images'] for change in changes} != expected_images:
        raise Review('iomp_inline_image_selection_changed')
    return updated


def _normalize_unsupported_pairs(payload):
    root = payload['ape']
    selected = {}
    try:
        for path, node in _walk(root):
            html = node.get('fields', {}).get('html')
            if isinstance(html, str) and IMAGE_TAG.search(html) and _ordinary_pair(node, html):
                probe = {**payload, 'ape': {**root, 'children': [node]}}
                issues = set(plan_import(probe)['issues'])
                if issues - {'empty_lesson'} == {'unsafe_or_unrecognized_html'}:
                    selected[path] = 2
        if selected and 'unsafe_or_unrecognized_html' in plan_import(payload)['issues']:
            payload['ape'] = _split_selected(root, selected)
    except (Review, ValueError, RecursionError):
        # Leave the source intact for the normal import review.
        return


def reviewed_image_url(value):
    """Recognize the original shared GetCourse illustration at its exact URL."""
    return (isinstance(value, str) and value.isascii()
            and hashlib.sha256(value.encode()).hexdigest() == IMAGE_URL_DIGEST)


def normalize_iomp_material(payload):
    if (payload.get('account'), payload.get('source_origin'), payload.get('format')) != (
        'iomp', 'https://shop.iomp.ru', 'ape',
    ):
        return
    identity = (payload.get('course_id'), payload.get('lesson_id'))
    expected = REVIEWED_NODES.get(identity)
    if expected is None:
        _normalize_unsupported_pairs(payload)
        return
    root = payload['ape']
    children = root['children']
    for index, node in enumerate(children):
        material = {key: value for key, value in node.items() if key != 'id'}
        if _digest(material) != expected:
            continue
        if identity in {('52', '336'), ('65', '481')}:
            del children[index]
        elif identity == ('44', '243'):
            # Only the surrounding copied GetCourse DIVs contain layout and
            # widget chrome. All inner labels, anchors and text styles survive.
            markup = re.sub(r'</?div\b[^>]*>', '', node['fields']['html'])
            make_html_block(markup)
            node['fields']['html'] = markup
        else:
            payload['ape'] = _split_selected(root, {(index,): 1})
        break
    _normalize_unsupported_pairs(payload)
