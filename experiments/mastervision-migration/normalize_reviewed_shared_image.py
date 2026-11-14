"""One owner-approved image/self-link, using an already verified MV private URL.

The target path was read from both reference File rows, never predicted from an
AVO URL or a content hash. The caller must verify the reference before import and
the new attachment, body image and link before any subsequent target mutation.
"""
import copy
import hashlib
from html import escape
import json
import re
import uuid

from importer import ACCOUNT, ORIGIN, SITE, Review

CODE = 'reviewed_shared_image_selflink_preserved'
PINNED_TARGET_PATH = '/private/files/avo-7b1f40c6d51a90be7eace51caac2832e37503e846c597c05293b5ae900eec106.jpg'
PINNED_TARGET_PATH_SHA256 = '0cdd58d5ea53c87937f677da940296bc80c59ec3d857d47c174f2a206b7e5272'
IMAGE_SHA256 = '7b1f40c6d51a90be7eace51caac2832e37503e846c597c05293b5ae900eec106'
IMAGE_MD5 = '9ee81b9bee06c4e2da321e7d0608cdf3'
IMAGE_SIZE = 221327
FILE_OWNER = 'Administrator'
SOURCE_URL_SHA256 = 'f7ca50c355f1de74132ff4f072bed77ae52d7ad2a0bd9500726abc9c8afa757e'
BINDINGS = {(634, 7364): {
    'ape_sha256': '93c4d76ec18d96dd84e655e02457746aa149f2a09302c710d62bcfa5db5d6628',
    'path': (4,),
    'node_sha256': 'e7b86561f3f1b64eff1ceefd49b49bd6b1d35bc9fec5b3cebb255cc139b0ac7a',
    'style_sha256': 'bc41cd4c18cb722ce66eaa375ed43d71f1a9aa3e1990df7684782096934c3858',
    'source_url_sha256': SOURCE_URL_SHA256,
}}


def _review(code='reviewed_shared_image_source_invalid'):
    raise Review(code)


def _sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _digest(value, *, ascii=False):
    try:
        return _sha(json.dumps(value, ensure_ascii=ascii, sort_keys=True, separators=(',', ':'), allow_nan=False))
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _review()


def _number(value):
    if type(value) is int and 0 < value <= 2**31 - 1: return value
    if isinstance(value, str) and re.fullmatch('[1-9][0-9]{0,9}', value) and int(value) <= 2**31 - 1: return int(value)


def normalize_reviewed_shared_image(ape, course_id, lesson_id, validate):
    if (ACCOUNT, ORIGIN, SITE) != ('mastervision', 'https://shop.mastervision.su', 'my-lk.mastervision.su'):
        _review('reviewed_shared_image_account_mismatch')
    context = (_number(course_id), _number(lesson_id))
    if (None in context or not callable(validate) or not isinstance(ape, dict)
            or ape.get('name') != 'page' or not isinstance(ape.get('children'), list)):
        _review()
    result = copy.deepcopy(ape); binding = BINDINGS.get(context)
    if binding is None: return result, []
    if _digest(ape) != binding['ape_sha256'] or binding['path'] != (4,) or len(ape['children']) <= 4:
        _review('reviewed_shared_image_source_changed')
    node = result['children'][4]
    if not isinstance(node, dict) or _digest(node) != binding['node_sha256']:
        _review('reviewed_shared_image_source_changed')
    fields = node.get('fields'); style = node.get('style')
    if (node.get('name') != 'image' or set(node) - {'id','name','fields','children','style'}
            or node.get('children', []) != [] or not isinstance(node.get('children', []), list)
            or not isinstance(fields, dict) or set(fields) != {'anchor','html','imageSrc','linkHref','linkTarget'}
            or fields.get('anchor') != '' or fields.get('html') != 'Изображение'
            or fields.get('linkTarget') is not True or not isinstance(fields.get('imageSrc'), str)
            or fields['linkHref'] != fields['imageSrc'] or not isinstance(style, dict)):
        _review()
    if (_sha(fields['imageSrc']) != binding['source_url_sha256']
            or _digest(style, ascii=True) != binding['style_sha256']):
        _review('reviewed_shared_image_source_changed')
    if (not re.fullmatch(r'/private/files/[A-Za-z0-9][A-Za-z0-9_.-]{0,180}', PINNED_TARGET_PATH)
            or '..' in PINNED_TARGET_PATH or _sha(PINNED_TARGET_PATH) != PINNED_TARGET_PATH_SHA256):
        _review()
    url = 'https://' + SITE + PINNED_TARGET_PATH
    try: validate('<a href="' + escape(url, quote=True) + '">Изображение</a>')
    except (ValueError, UnicodeError, RecursionError): _review()
    ident = str(uuid.uuid5(uuid.NAMESPACE_URL, 'mastervision:634:7364:selflink:' + binding['node_sha256']))
    pending = [result]
    while pending:
        current = pending.pop()
        if current.get('id') == ident: _review()
        pending.extend(current.get('children', []))
    source = fields['imageSrc']; label = fields['html']
    node['fields'] = {'anchor': '', 'imageSrc': source}
    button = {'id': ident, 'name': 'button', 'fields': {'anchor': '', 'html': label,
        'linkType': 'url', 'url': url, 'blank': True}}
    result['children'].insert(5, button)
    if (node['fields']['imageSrc'] != source or node['style'] != style
            or result['children'][:4] != ape['children'][:4]
            or result['children'][6:] != ape['children'][5:]):
        _review('reviewed_shared_image_material_mismatch')
    return result, [{'path': [4], 'code': CODE, 'source_ape_sha256': binding['ape_sha256'],
        'source_node_sha256': binding['node_sha256'], 'source_url_sha256': binding['source_url_sha256'],
        'style_sha256': binding['style_sha256'], 'target_path_sha256': PINNED_TARGET_PATH_SHA256,
        'image_sha256': IMAGE_SHA256, 'image_md5': IMAGE_MD5, 'image_size': IMAGE_SIZE,
        'file_owner': FILE_OWNER, 'source_link_target': True, 'source_label_preserved': True,
        'link_materialized_as_separate_button': True, 'requires_post_import_same_url_verification': True}]
