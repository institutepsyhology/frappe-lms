"""Flatten inert image-only resize spans without changing any lesson material."""
import copy
from html import escape, unescape
import re

from importer import Review
from normalize_inline_images import Document, Element, _probe
from normalize_static_presentation import _material
from normalize_legacy_html_decorations import _has_content_style

CODE = 'image_wrapper_layout_normalized'


class _Document(Document):
    def handle_starttag(self, tag, attrs):
        start, parent = self.position(), self.stack[-1]
        super().handle_starttag(tag, attrs)
        parent.children[-1].start = start


def _image_only(node):
    pending, images = [node], 0
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            if unescape(item).strip(' \t\r\n\f\u00a0'): return False
        elif item.tag == 'img': images += 1
        elif item.tag == 'span': pending.extend(item.children)
        else: return False
    return images == 1


def _opening(node):
    if node.tag != 'span' or set(node.attrs) != {'style'} or not _image_only(node): return None
    css = node.attrs['style']
    if not isinstance(css, str) or len(css) > 2000: return None
    seen, kept, removed = set(), [], 0
    for piece in css.split(';'):
        if not piece.strip(): continue
        if ':' not in piece: return None
        key, value = (part.strip() for part in piece.split(':', 1)); key = key.lower()
        if key in seen: return None
        seen.add(key)
        if key == 'display':
            if value.lower() != 'inline-block': return None
            removed += 1
        elif key == 'height':
            match = re.fullmatch(r'([1-9][0-9]{0,3}(?:\.[0-9]{1,3})?)px', value)
            if not match or float(match[1]) > 4096: return None
            removed += 1
        else: kept.append(piece)
    if not removed: return None
    rest = ';'.join(kept)
    return '<span' + (' style="' + escape(rest, quote=True) + '"' if rest.strip() else '') + '>'


def _clean(markup, validate):
    if not isinstance(markup, str) or not re.search(r'<\s*img\b', markup, re.I): return None
    try:
        document = _Document(markup)
        try:
            validate(_probe(document.root))
            return None  # Previously accepted source stays byte-identical.
        except (ValueError, UnicodeError, RecursionError): pass
        edits, pending = [], list(document.root.children)
        while pending:
            node = pending.pop()
            if isinstance(node, Element):
                opening = _opening(node)
                if opening is not None: edits.append((node.start, node.start + len(node.opening), opening))
                pending.extend(node.children)
        if not edits: return None
        cleaned = markup
        for start, end, opening in sorted(edits, reverse=True): cleaned = cleaned[:start] + opening + cleaned[end:]
        prepared = Document(cleaned)
        validate(_probe(prepared.root))
    except (Review, ValueError, UnicodeError, RecursionError): return None
    if _material(markup) != _material(cleaned): raise Review('image_wrapper_material_mismatch')
    return cleaned, len(edits), len(document.images)


def normalize_image_wrapper_layout(ape, validate_static):
    if not callable(validate_static) or not isinstance(ape, dict) or ape.get('name') != 'page':
        raise Review('image_wrapper_source_invalid')
    result, changes, visited = copy.deepcopy(ape), [], 0

    def walk(node, path, protected=False):
        nonlocal visited
        visited += 1
        if visited > 150000 or len(path) > 100 or not isinstance(node, dict): raise Review('image_wrapper_source_invalid')
        fields, children = node.get('fields', {}), node.get('children', [])
        if not isinstance(fields, dict) or not isinstance(children, list): raise Review('image_wrapper_source_invalid')
        protected = protected or fields.get('anchor') not in (None, '') or any(
            fields.get(key) not in (None, '', False, [], {}) for key in ('visibleConditions','displayDelay'))
        allowed = {'html','anchor'} | ({'format'} if node.get('name') == 'header' else set())
        if (not protected and node.get('name') in {'text','code','header'} and not children
                and not set(fields) - allowed and not set(node) - {'id','name','fields','children','style'}
                and not _has_content_style(node.get('style'))):
            cleaned = _clean(fields.get('html'), validate_static)
            if cleaned:
                fields['html'], wrappers, images = cleaned
                changes.append({'path':list(path),'code':CODE,'wrappers':wrappers,'images':images})
        for index, child in enumerate(children): walk(child, path + [index], protected)

    walk(result, [])
    return result, changes
