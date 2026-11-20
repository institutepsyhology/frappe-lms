"""Resolve reviewed IOMP order buttons using their own lesson previews."""

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
    ('179', '3017'): ('{goods_ordering_746}', '2794e97b1781873e7b74ca9cfc96d0a3cb31deddf56911458862326da4a1cfee'),
    ('184', '3070'): ('{goods_ordering_750}', '5d298fd2ce3794c18bab93c44b1bd23a0dd6695f76441450edf12a651d000bbd'),
    ('184', '3073'): ('{goods_ordering_750}', 'ae883abfca7c2121e3afbc7ba419c77d4ffa1fa58623e8294e3af2a6b8a201f0'),
    ('185', '3079'): ('{goods_ordering_750}', '0c6fa9ebcf5fb2a0b60d9bca6c25f9a3737c6135fa1fcb9d6e553b0467c14359'),
    ('188', '3138'): ('{goods_ordering_728}', 'f1594e5f998cac2bd1128820d39b55d9e95d6e1879cf05f02dae1b3a700090fc'),
    ('188', '3140'): ('{goods_ordering_728}', 'f1594e5f998cac2bd1128820d39b55d9e95d6e1879cf05f02dae1b3a700090fc'),
}
CONSULTATION = '820ed5d88811f6437ce9e2baf72a260574aab436310d35731a8f433f3aedaa20'
FORM_750 = '6e14400a9d7cb6a58f00845d3e52fac0cf4cf40028ef6ffe51fb57e0348934d2'
FORM_728 = '7e84d934230ee6971117593e2c23cb33e5ddc4d3063bc72b7384c926ca959865'
FIRST_CAPTURE = {('178', '3002'), ('194', '3288'), ('207', '3498')}
PREVIEW_FINGERPRINTS = {
    ('178', '3002'): CONSULTATION,
    ('194', '3288'): CONSULTATION,
    ('207', '3498'): '294777ca9b73ae9ee6801e9cea301873a8dd5671b05648949e5e35a43dc2bd45',
    ('179', '3017'): 'c7d30b141edeef731d79d196375bf539d3313348c9d4e35a44340e08a13320e5',
    ('184', '3070'): FORM_750, ('184', '3073'): FORM_750, ('185', '3079'): FORM_750,
    ('188', '3138'): FORM_728, ('188', '3140'): FORM_728,
}


def _preview_url(archive, key):
    try:
        receipt = 'preview-offer-links.json' if key in FIRST_CAPTURE else 'preview-offer-links-20261120.json'
        capture = json.loads((archive / receipt).read_text(encoding='utf-8-sig'))
        if (capture['account'], capture['source_origin']) != ('iomp', ORIGIN):
            raise ValueError
        url, = [row['url'] for row in capture['links']
                if (str(row['course_id']), str(row['lesson_id'])) == key]
        address = urlsplit(url)
        query = parse_qsl(address.query, keep_blank_values=True, strict_parsing=True)
        product = SOURCE_BUTTONS[key][0].removeprefix('{goods_ordering_').removesuffix('}')
        if (address.scheme != 'https' or address.netloc != 'shop.iomp.ru' or address.path != '/'
                or address.fragment or len(query) != 4
                or dict(query) != {'r': 'ordering/cart/as1', 'id': product, 'clean': 'true', 'lg': 'ru'}
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
