"""Reuse an earlier source only when changed APE UUIDs are provably unused.

No fields, URLs, content, settings, node order or source identity are normalized.
The caller archives the fresh observation separately before using this copy.
"""
import copy
import math
import re

from importer import Review, Stop

ACCOUNT = 'mastervision'
ORIGIN = 'https://shop.mastervision.su'
CODE = 'ape_unused_ids_reused'
UUID = re.compile(r'(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})')


def _id(value):
    if type(value) is int: return 0 < value <= 2**53 - 1
    return isinstance(value, str) and bool(re.fullmatch('[1-9][0-9]{0,15}', value)) and int(value) <= 2**53 - 1


def _identity(payload):
    if not isinstance(payload, dict) or payload.get('account') != ACCOUNT or payload.get('source_origin') != ORIGIN:
        raise Stop('canonical_source_account_mismatch')
    if not _id(payload.get('course_id')) or not _id(payload.get('lesson_id')):
        raise Stop('canonical_source_identity_invalid')
    return tuple((type(payload[key]), payload[key]) for key in ('course_id','lesson_id'))


def _json(value):
    pending, count = [(value,0)], 0
    while pending:
        node, depth = pending.pop(); count += 1
        if count > 150000 or depth > 128: raise Review('canonical_source_invalid')
        if type(node) is dict:
            if any(type(key) is not str for key in node): raise Review('canonical_source_invalid')
            pending.extend((child,depth + 1) for child in node.values())
        elif type(node) is list:
            pending.extend((child,depth + 1) for child in node)
        elif node is not None and type(node) not in (str,int,float,bool): raise Review('canonical_source_invalid')
        elif type(node) is float and not math.isfinite(node): raise Review('canonical_source_invalid')


def _nodes(payload):
    """Return only IDs of actual APE nodes reached through children edges."""
    root = payload.get('ape')
    if payload.get('format') != 'ape' or not isinstance(root, dict) or root.get('name') != 'page' or not isinstance(root.get('children'), list): return {}, False
    pending, ids, seen = [(root,('ape',))], {}, set()
    while pending:
        node, path = pending.pop()
        if not isinstance(node, dict) or not isinstance(node.get('name'), str) or not node['name']: return {}, False
        if 'id' in node:
            ident = node['id']
            if not isinstance(ident, str) or ident in seen: return {}, False
            seen.add(ident); ids[path + ('id',)] = ident
        children = node.get('children', [])
        if not isinstance(children, list): return {}, False
        pending.extend((child,path + ('children',index)) for index,child in enumerate(children))
    return ids, True


def _same(left, right, allowed, changed, path=()):
    # bool/int/float and all other JSON types stay distinct. JSON object key
    # order is immaterial; array order and every source value are exact.
    if type(left) is not type(right): return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same(left[key],right[key],allowed,changed,path + (key,)) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_same(a,b,allowed,changed,path + (index,)) for index,(a,b) in enumerate(zip(left,right)))
    if type(left) is float: return left.hex() == right.hex()
    if left == right: return True
    if path in allowed and isinstance(left, str) and UUID.fullmatch(left) and UUID.fullmatch(right):
        changed.append((path,left,right)); return True
    return False


def _referenced(payload, own_path, tokens):
    pending = [(payload,())]
    while pending:
        value, path = pending.pop()
        if path == own_path: continue
        if isinstance(value, dict):
            for key, child in value.items():
                if any(token in key for token in tokens): return True
                pending.append((child,path + (key,)))
        elif isinstance(value, list):
            pending.extend((child,path + (index,)) for index,child in enumerate(value))
        elif isinstance(value, str) and any(token in value for token in tokens): return True
    return False


def canonical_payload(current_payload, historical_payloads):
    """Return a deep source copy and fixed codes, selecting earliest equivalent.

    History must already be ordered oldest first by the caller. An exact
    duplicate needs no warning. Genuine source differences remain the current
    payload so the unchanged MCP fingerprint guard can require review.
    """
    identity = _identity(current_payload); _json(current_payload)
    if not isinstance(historical_payloads, (list,tuple)): raise Review('canonical_source_invalid')
    # Detect a polluted account/source history even if an earlier row matches.
    for candidate in historical_payloads:
        if _identity(candidate) != identity: raise Stop('canonical_source_identity_mismatch')
        _json(candidate)
    current_ids, current_valid = _nodes(current_payload)
    for candidate in historical_payloads:
        changed = []
        if _same(candidate,current_payload,set(),changed): return copy.deepcopy(candidate), []
        candidate_ids, candidate_valid = _nodes(candidate)
        if not current_valid or not candidate_valid or candidate_ids.keys() != current_ids.keys(): continue
        changed = []
        if not _same(candidate,current_payload,set(current_ids),changed) or not changed: continue
        if any(_referenced(payload,path,(old,new)) for path,old,new in changed for payload in (candidate,current_payload)): continue
        return copy.deepcopy(candidate), [CODE]
    return copy.deepcopy(current_payload), []
