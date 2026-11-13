"""Owner-approved omission of one exact MV CSS image rotation.

All image source references and binary files stay unchanged. The caller retains
the complete original APE; this helper changes only the reviewed span opening.
"""
import copy
import hashlib
import re

from importer import ACCOUNT, ORIGIN, Review
from normalize_image_wrapper_layout import _Document, _image_only, _clean as clean_wrappers
from normalize_inline_images import Document, Element, _probe
from normalize_legacy_html_decorations import _has_content_style
from normalize_static_presentation import _material

CODE = 'owner_reviewed_image_rotation_omitted'
CONTEXT = (520, 5176)
PATH = (2,)
HTML_SHA = '83b86c4eee3e576f7e4a4f2047345db5f53b23fc3e2d02ca1604c3bcaf84fa48'
OUTER_SHA = '76d78fdff74ea56abb68f49b3777212c907a5324fca4b6cfa8c6bd9f09412974'
URL_SHA = '8bfb8a27b09c6bd30f09a8c7a9091267670ea993168e2c867de17bd76f12e8bc'
RADIANS = 3.14
CSS = 'transform:rotate(3.14rad)'


def _review(code='reviewed_rotation_requires_review'): raise Review(code)


def _binding():
    if (ACCOUNT, ORIGIN) != ('mastervision', 'https://shop.mastervision.su'):
        _review('reviewed_rotation_account_mismatch')


def _sha(value):
    if not isinstance(value, str): _review()
    try: return hashlib.sha256(value.encode('utf-8')).hexdigest()
    except UnicodeError: _review()


def _number(value):
    if type(value) is int and value > 0: return value
    if isinstance(value, str) and re.fullmatch('[1-9][0-9]{0,9}', value): return int(value)


def _receipt():
    return {'path': list(PATH), 'code': CODE, 'html_sha256': HTML_SHA,
            'outer_sha256': OUTER_SHA, 'url_sha256': URL_SHA, 'radians': RADIANS,
            'action': 'omit_css_rotation', 'source_image_unchanged': True}


def _render(node):
    if isinstance(node, str): return node
    return node.opening + ''.join(_render(child) for child in node.children) + node.closing


def _source(ape):
    if not isinstance(ape, dict) or ape.get('name') != 'page': return None
    node = ape
    for index in PATH:
        if (not isinstance(node, dict) or not isinstance(node.get('fields', {}), dict)
                or set(node.get('fields', {})) - {'anchor', 'visibleConditions', 'displayDelay'}
                or node.get('fields', {}).get('anchor') not in (None, '')
                or any(node.get('fields', {}).get(k) is not None for k in ('visibleConditions', 'displayDelay'))
                or _has_content_style(node.get('style'))): return None
        children = node.get('children')
        if not isinstance(children, list) or not 0 <= index < len(children): return None
        node = children[index]
    if (not isinstance(node, dict) or node.get('name') != 'text' or node.get('children')
            or set(node) - {'id', 'name', 'fields', 'style', 'children'}
            or not isinstance(node.get('fields'), dict) or set(node['fields']) - {'anchor', 'html'}
            or node['fields'].get('anchor') not in (None, '') or _has_content_style(node.get('style'))): return None
    html = node['fields'].get('html')
    if not isinstance(html, str) or len(html) > 200000 or _sha(html) != HTML_SHA: return None
    document = _Document(html); pending = [document.root]; rotations, target_images = [], []
    while pending:
        item = pending.pop()
        if not isinstance(item, Element): continue
        if item.tag == 'span' and item.attrs.get('style') == CSS: rotations.append(item)
        if item.tag == 'img' and _sha(item.attrs.get('src')) == URL_SHA: target_images.append(item)
        pending.extend(reversed(item.children))
    if len(rotations) != 1 or len(target_images) != 1: _review()
    rotation = rotations[0]
    if (rotation.attrs != {'style': CSS} or not _image_only(rotation)
            or _sha(_render(rotation)) != OUTER_SHA): _review()
    descendants, images = [rotation], []
    while descendants:
        item = descendants.pop()
        if isinstance(item, Element):
            if item.tag == 'img': images.append(item)
            descendants.extend(item.children)
    if images != target_images: _review()
    return node, html, rotation


def normalize_reviewed_image_rotation(ape, course_id, lesson_id, validate_static):
    """Remove only the exact image-only CSS rotation; preserve all other bytes."""
    _binding()
    if not isinstance(ape, dict) or ape.get('name') != 'page' or not callable(validate_static):
        _review('reviewed_rotation_source_invalid')
    result = copy.deepcopy(ape)
    if (_number(course_id), _number(lesson_id)) != CONTEXT: return result, []
    found = _source(result)
    if found is None: return result, []
    node, html, rotation = found
    cleaned = html[:rotation.start] + '<span>' + html[rotation.start + len(rotation.opening):]
    if _material(html) != _material(cleaned): _review('reviewed_rotation_material_mismatch')
    # Keep the generic image wrapper/extraction pass separate. Its existing
    # strict probe must admit the remaining HTML once the sole rotation is gone.
    candidate = clean_wrappers(cleaned, validate_static)
    probe = candidate[0] if candidate else cleaned
    try: validate_static(_probe(Document(probe).root))
    except (ValueError, UnicodeError, RecursionError): _review()
    node['fields']['html'] = cleaned
    return result, [_receipt()]

