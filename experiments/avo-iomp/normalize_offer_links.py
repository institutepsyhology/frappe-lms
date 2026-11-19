"""Resolve three reviewed IOMP editor placeholders using their own lesson previews."""

import hashlib
import json
from urllib.parse import parse_qsl, urlsplit

from importer import Review
from normalize_reviewed_pairs import _digest


ORIGIN = 'https://shop.iomp.ru'
SOURCE_BUTTONS = {
    ('178', '3002'): ('{goods_ordering_738}', '90af019bbfb3c259a36c654f6e0bb53834a3f6a6cadeb1249f2f8262855e6417'),
    ('194', '3288'): ('{goods_ordering_738}', '6ef58852ed7eb66295db8ab7add5fac0deed2474cb099c834aa426b5b34dd010'),
    ('207', '3498'): ('{goods_ordering_868}', 'f24d06f81edd11dd87dc125d7f53da3bb286742248531feac195ea43944c7be4'),
}
CONSULTATION = '820ed5d88811f6437ce9e2baf72a260574aab436310d35731a8f433f3aedaa20'
PREVIEW_FINGERPRINTS = {
    ('178', '3002'): CONSULTATION,
    ('194', '3288'): CONSULTATION,
    ('207', '3498'): '294777ca9b73ae9ee6801e9cea301873a8dd5671b05648949e5e35a43dc2bd45',
}


def _preview_url(archive, key):
    try:
        capture = json.loads((archive / 'preview-offer-links.json').read_text(encoding='utf-8-sig'))
        if (capture['account'], capture['source_origin']) != ('iomp', ORIGIN):
            raise ValueError
        url, = [row['url'] for row in capture['links']
                if (str(row['course_id']), str(row['lesson_id'])) == key]
        address = urlsplit(url)
        query = parse_qsl(address.query, keep_blank_values=True, strict_parsing=True)
        keys = [name for name, _ in query]
        if (address.scheme != 'https' or address.netloc != 'shop.iomp.ru' or address.path != '/'
                or address.fragment or len(keys) != len(set(keys)) or set(keys) != {'r', 'id', 'clean', 'lg'}
                or hashlib.sha256(url.encode()).hexdigest() != PREVIEW_FINGERPRINTS[key]):
            raise ValueError
        return url
    except (OSError, TypeError, AttributeError, KeyError, ValueError) as exc:
        raise Review('iomp_offer_preview_requires_verification') from exc


def resolve_offer_link(payload, archive):
    if (payload.get('account'), payload.get('source_origin'), payload.get('format')) != ('iomp', ORIGIN, 'ape'):
        return
    key = str(payload['course_id']), str(payload['lesson_id'])
    if key not in SOURCE_BUTTONS:
        return
    placeholder, fingerprint = SOURCE_BUTTONS[key]
    url = _preview_url(archive, key)
    candidates = []
    pending = [payload['ape']]
    while pending:
        node = pending.pop()
        pending.extend(node.get('children', []))
        fields = node.get('fields', {})
        if node.get('name') != 'button' or fields.get('url') not in (placeholder, url):
            continue
        # Compare the complete authored button, including caption, behavior and layout.
        original = {**node, 'fields': {**fields, 'url': placeholder}}
        if _digest(original) != fingerprint:
            raise Review('iomp_offer_button_changed')
        candidates.append(fields)
    if len(candidates) != 1:
        raise Review('iomp_offer_button_changed')
    candidates[0]['url'] = url
