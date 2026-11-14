"""Omit only the seven lessons' exact owner-approved obsolete purchase buttons.

The untouched source APE belongs in the caller's private snapshot. This module
has no URL literals, network calls, target writes, or cross-account fallbacks.
"""
import copy
import hashlib
import json
import re

from importer import ACCOUNT, ORIGIN, Review
from normalize_remaining_static_material import _number

CODE = 'owner_obsolete_purchase_button_omitted'
APPROVED = {
    (529, 5478): ('f352898d699e49d2d5be76b4a3a8bbd1dec774890a1fdc00f92d501e20b65734', (
        ((6,), 'c47a419eb1c249213045ce82d0357b3e4761af0dd9472221b83764125d5a4bc3'),)),
    (529, 5498): ('15ca1e2a301c746b02e321e9d880e5318ccabb14bda76fc7cb5ffca3a31d16dc', (
        ((5,), 'c47a419eb1c249213045ce82d0357b3e4761af0dd9472221b83764125d5a4bc3'),)),
    (529, 5499): ('4332d48c8b82561876790c06de487b1505ffd776251354cc1e87f98bbf8b6f13', (
        ((5,), 'c47a419eb1c249213045ce82d0357b3e4761af0dd9472221b83764125d5a4bc3'),)),
    (558, 5955): ('911609a391a2634818f528a76ada83a02bc0c0591dc5da0a16085d2b58dac4b3', (
        ((4, 1, 0), '543a77a10939c3943b6aeb9e6b920ae1429f0eac920ce35150666ff1a28e03c6'),
        ((6, 1, 0), 'e91316838211b910b3c88eec7dc0cb40a2e872e72e0c0553e92be781b39f0708'))),
    (562, 5977): ('5c6702b151869001324edfb690f051ffa4495d3b35a04eb8dd53a0113f3509df', (
        ((5,), '684d24a2e6508511572a500c7290f8aa9936a7f92085ce91173fc35b6a759210'),)),
    (562, 5981): ('aaa52f87fd65abf525208fe8b83d3be5683374e35ffd68cc4084648be0ed4aa2', (
        ((5,), '684d24a2e6508511572a500c7290f8aa9936a7f92085ce91173fc35b6a759210'),)),
    (562, 5982): ('afda2bc29d178761a1d7a6ca8c661ebc88cb4b45b47c0c7191c5defd08e7d9fc', (
        ((5,), '684d24a2e6508511572a500c7290f8aa9936a7f92085ce91173fc35b6a759210'),)),
}


def _sha(value):
    try:
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise Review('owner_purchase_source_invalid') from None


def normalize_owner_purchase_buttons(ape, course_id, lesson_id):
    if (ACCOUNT, ORIGIN) != ('mastervision', 'https://shop.mastervision.su'):
        raise Review('owner_purchase_account_mismatch')
    context = (_number(course_id), _number(lesson_id))
    if (None in context or not isinstance(ape, dict) or ape.get('name') != 'page'
            or not isinstance(ape.get('children'), list)):
        raise Review('owner_purchase_source_invalid')
    binding = APPROVED.get(context)
    try: copied = copy.deepcopy(ape)
    except (TypeError, RecursionError): raise Review('owner_purchase_source_invalid') from None
    if binding is None: return copied, []
    expected_ape, buttons = binding
    if _sha(ape) != expected_ape:
        raise Review('owner_purchase_source_changed')
    changes, removals = [], []
    for path, expected_node in buttons:
        try:
            parent = copied
            for index in path[:-1]: parent = parent['children'][index]
            node = parent['children'][path[-1]]
            fields = node['fields']
            if (node.get('name') != 'button' or node.get('children')
                    or not isinstance(fields, dict) or fields.get('linkType') != 'url'
                    or not isinstance(fields.get('url'), str)
                    or not re.fullmatch(r'\{goods_ordering_[1-9][0-9]*\}', fields['url'])):
                raise ValueError()
        except (KeyError, IndexError, TypeError, ValueError):
            raise Review('owner_purchase_source_invalid') from None
        if _sha(node) != expected_node:
            raise Review('owner_purchase_source_changed')
        removals.append((path, parent))
        changes.append({'path': list(path), 'code': CODE, 'source_node_sha256': expected_node})
    # Reverse original paths keep siblings and every surviving node untouched.
    for path, parent in sorted(removals, key=lambda item: item[0], reverse=True):
        del parent['children'][path[-1]]
    return copied, changes
