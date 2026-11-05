"""Decode an already-extracted AWO APE packed block, without evaluating JavaScript.

The underlying decoded schema has not been established; it may be JSON or text.
This module performs no I/O, networking, JavaScript evaluation, or database writes.
"""
from dataclasses import dataclass
import base64
import binascii
import hashlib
import json
import re
import zlib


@dataclass(frozen=True)
class Limits:
    max_js_chars: int = 24 * 1024 * 1024
    max_base64_chars: int = 16 * 1024 * 1024
    max_compressed_bytes: int = 12 * 1024 * 1024
    max_output_bytes: int = 64 * 1024 * 1024
    max_json_depth: int = 128


class PackedError(ValueError):
    pass


def unquote_js_string(token, limits=Limits()):
    r"""Decode a quoted JS string literal containing ASCII base64, without eval.

    Supports ordinary characters, escaped quotes/slash/backslash, \xNN and
    \uNNNN; unsupported JS syntax is rejected. No line continuations.
    """
    if not isinstance(token, str) or len(token) > limits.max_js_chars:
        raise PackedError('invalid or oversized JS token')
    if len(token) < 2 or token[0] not in "\"'" or token[-1] != token[0]:
        raise PackedError('expected a quoted JS string token')
    quote = token[0]
    result = []
    i = 1
    while i < len(token) - 1:
        c = token[i]
        if c == quote or c in '\r\n':
            raise PackedError('unescaped quote or newline')
        if c != '\\':
            result.append(c)
            i += 1
            continue
        i += 1
        if i >= len(token) - 1:
            raise PackedError('truncated escape')
        esc = token[i]
        if esc in "\\/'\"":
            result.append(esc)
            i += 1
        elif esc in ('x', 'u'):
            size = 2 if esc == 'x' else 4
            digits = token[i + 1:i + 1 + size]
            if len(digits) != size or not re.fullmatch(r'[0-9a-fA-F]+', digits):
                raise PackedError('invalid hex escape')
            result.append(chr(int(digits, 16)))
            i += 1 + size
        else:
            raise PackedError('unsupported JS escape')
        if len(result) > limits.max_base64_chars:
            raise PackedError('base64 size limit exceeded')
    result = ''.join(result)
    if len(result) > limits.max_base64_chars:
        raise PackedError('base64 size limit exceeded')
    return result


def _check_depth(text, limit):
    depth = 0
    in_string = False
    escaped = False
    for c in text:
        if in_string:
            if escaped:
                escaped = False
            elif c == '\\':
                escaped = True
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
        elif c in '[{':
            depth += 1
            if depth > limit:
                raise PackedError('JSON nesting limit exceeded')
        elif c in ']}':
            depth -= 1


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PackedError('duplicate JSON key')
        result[key] = value
    return result


def _reject_constant(value):
    raise PackedError('nonstandard JSON constant: ' + value)


def decode_packed_block(encoded, limits=Limits()):
    """Decode strict base64 + zlib; return exact text and optional parsed JSON.

    Payloads which are valid UTF-8 but not JSON are preserved as text and marked
    as unrecognized: the caller decides whether that requires operator review.
    """
    if not isinstance(encoded, str) or len(encoded) > limits.max_base64_chars:
        raise PackedError('invalid or oversized base64 input')
    try:
        encoded_bytes = encoded.encode('ascii')
        compressed = base64.b64decode(encoded_bytes, validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
        raise PackedError('invalid base64') from exc
    if len(compressed) > limits.max_compressed_bytes:
        raise PackedError('compressed input size limit exceeded')
    try:
        dec = zlib.decompressobj()
        raw = dec.decompress(compressed, limits.max_output_bytes + 1)
    except zlib.error as exc:
        raise PackedError('invalid zlib stream') from exc
    if len(raw) > limits.max_output_bytes or dec.unconsumed_tail:
        raise PackedError('decompressed size limit exceeded')
    if not dec.eof:
        raise PackedError('truncated zlib stream')
    if dec.unused_data:
        raise PackedError('trailing data after zlib stream')
    try:
        text = raw.decode('utf-8', errors='strict')
    except UnicodeDecodeError as exc:
        raise PackedError('decoded output is not UTF-8') from exc
    _check_depth(text, limits.max_json_depth)
    try:
        value = json.loads(text, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
    except json.JSONDecodeError:
        value = None
        kind = 'unrecognized_text'
        diagnostics = ['decoded content is not valid JSON; preserve and review']
    except (RecursionError, ValueError) as exc:
        if isinstance(exc, PackedError):
            raise
        raise PackedError('invalid or overcomplex JSON') from exc
    else:
        kind = 'json'
        diagnostics = []
    return {'text': text, 'json': value, 'kind': kind,
            'sha256': hashlib.sha256(raw).hexdigest(),
            'output_bytes': len(raw), 'compressed_bytes': len(compressed),
            'diagnostics': diagnostics, 'schema_confirmed': False}


def decode_ape_payload(payload, limits=Limits()):
    """Decode an already-parsed payload; no extraction of JS object expressions."""
    if not isinstance(payload, dict) or type(payload.get('formatVersion')) is not int:
        raise PackedError('invalid APE payload')
    if payload['formatVersion'] != 4 or payload.get('packed') is not True:
        raise PackedError('unsupported APE format or packing')
    result = decode_packed_block(payload.get('block'), limits)
    if result['kind'] != 'json' or not isinstance(result['json'], dict):
        raise PackedError('APE v4 decoded root is not a JSON object')
    root = result['json']
    if root.get('name') != 'page' or not isinstance(root.get('children'), list):
        result['diagnostics'].append('unexpected APE v4 root shape; preserve and review')
    result['format_version'] = 4
    return result
