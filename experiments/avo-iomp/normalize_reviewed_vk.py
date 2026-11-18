"""Keep the explicitly labelled YouTube and VK players of IOMP 48/263 in order."""

import hashlib
import json
import re

from importer import Review
from lms.lms.avo_html_fragment import make_html_block


# Both archived captures agree on the entire section, including the two
# captions, player identities, settings and column order. No media URL is stored here.
SOURCE_SECTION = '65fe82b5073b7dc3d8d66a510634aae0b32eff9f8ef8a95b89429c5507c8f8f0'
NORMALIZED_SECTION = '66e8069dcd661f4010acecf11be0e872b34d29e5a87a74ab127898dbba9e65dc'


def section_digest(section):
    raw = json.dumps(section, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(raw.encode('ascii')).hexdigest()


def normalize_reviewed_vk(payload):
    if tuple(payload.get(key) for key in ('account', 'source_origin', 'format', 'course_id', 'lesson_id')) != (
        'iomp', 'https://shop.iomp.ru', 'ape', '48', '263',
    ):
        return
    sections = payload['ape'].get('children')
    if not isinstance(sections, list) or len(sections) < 2:
        raise Review('reviewed_vk_source_changed')
    group = sections[1]
    digest = section_digest(group)
    if digest == NORMALIZED_SECTION:
        return
    if digest != SOURCE_SECTION:
        raise Review('reviewed_vk_source_changed')

    primary, alternative = group['children']
    main_title, _ = primary['children']
    alt_title, vk = alternative['children']
    frame = vk['fields']['embeddedHtml']
    try:
        make_html_block(frame)
    except (ValueError, UnicodeError, RecursionError):
        raise Review('reviewed_vk_frame_invalid') from None

    # The native video choice supports YouTube/Rutube. For VK the equivalent
    # reviewed layout is a primary video and a separate validated HTML block.
    # Native headings keep the original labels legible on the theme background.
    for title in (main_title, alt_title):
        label = re.search(r'<strong>[^<>]+</strong>', title['fields']['html']).group()
        title.update(name='header', fields={'format': 'h4', 'html': '<h4>' + label + '</h4>'})
    vk.update(name='text', fields={'html': frame})
