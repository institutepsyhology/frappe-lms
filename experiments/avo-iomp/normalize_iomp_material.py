"""Prepare reviewed IOMP material and preserve static text around inline images."""

import hashlib
import json
import re

from importer import Review
from lms.lms.avo_html_fragment import make_html_block
from normalize_inline_images import normalize_inline_images
from normalize_legacy_html_decorations import _has_content_style


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
INLINE_IMAGE_COURSES = frozenset(str(course) for course in range(101, 109))


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
    if identity[0] in INLINE_IMAGE_COURSES:
        root = payload['ape']
        updated, changes = normalize_inline_images(root, make_html_block)
        for change in changes:
            source = root
            for index in change['path']:
                source = source['children'][index]
            if source.get('name') != 'text' or _has_content_style(source.get('style')):
                raise Review('iomp_inline_image_context_requires_review')
        if changes:
            payload['ape'] = updated
        return
    expected = REVIEWED_NODES.get(identity)
    if expected is None:
        return
    root = payload['ape']
    children = root['children']
    for index, node in enumerate(children):
        material = {key: value for key, value in node.items() if key != 'id'}
        raw = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        if hashlib.sha256(raw).hexdigest() != expected:
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
            updated, changes = normalize_inline_images(root, make_html_block)
            if len(changes) != 1 or changes[0]['path'] != [index] or changes[0]['images'] != 1:
                raise Review('iomp_inline_image_selection_changed')
            payload['ape'] = updated
        return
