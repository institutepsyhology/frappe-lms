"""Preserve reviewed GetCourse fragments while removing inert editor wrappers.

Only exact numeric identities, source-node/HTML hashes and paths are public.
All authored text, links, image sources and list semantics stay in source order.
The caller retains original APE and runs the existing image extraction pipeline.
"""
import copy
import hashlib
from html import escape
from html.parser import HTMLParser
import json
import re
from urllib.parse import urlsplit

from importer import ACCOUNT, ORIGIN, Review
from normalize_image_wrapper_layout import _clean as clean_image_wrappers
from normalize_inline_images import Document, _probe
from normalize_legacy_html_decorations import _has_content_style
from normalize_static_presentation import _material

CODE = 'reviewed_getcourse_wrappers_normalized'
BINDINGS = {
    (67, 101): ((0,), '40c38f1ea898f807edf940917ece19edbd3cf1cc4acc73a3fa1c782d0cec9017', 'e705ca7c0d0b4fd3d1add935fbf197a19894706f3a97b352a19383976f2b494d'),
    (174, 955): ((0,), '1b294568aad30382065018316f3846bf713ce270acec891f9f078fc907cacfce', 'e71780cf758616348be61b640ccf478f0d787fa93933fcfe78b445847a512d42'),
    (179, 994): ((0,), '3e1a156f49a1f4a582be6d5d3532a9b6458a6b1a2f6bfd9e3f93dab53b16fcbe', '525c070cf3a720478a077eb1f4f58cadfc080de2cedeb3543ae3a51935a63529'),
    (184, 1024): ((0,), 'ad31d9f945593dc69282c3e4f4bbc468365a681a98270e1aa6d3c17aced3fb8a', '38b3d0275ed2028ce3025b217ece788b5137d563d2cf4ea46e56bff8faabff49'),
    (187, 1037): ((0,), 'efa33c71b5958c0643152c9b53ebef87fc68a1a1061d1a002e3cdcf03f8887ca', '2cd860e2a805f91e238f498309fbb25b0f3225f3253920d8c7d10ee9d188da25'),
    (755, 8999): ((3,), '8bcbb5bba543cea1108617853211341713dce8326ebca4fd8999bfd108df55f8', '06971963815c423c5fabd2955e9c30379c86c33297bd24c3b6dd8fd1b6205d2c'),
}
VOID = {'img', 'br', 'hr', 'col'}
INERT_CLASSES = {'lesson-comment-block-1', 'lt-lesson-comment-block', 'o-lt-lesson-comment-block', 'video_wrapper'}
EDITOR_ATTRS = {'data-xdget-id', 'data-block-id', 'data-updated', 'data-code',
                'data-editable', 'data-main-class', 'data-param'}
GENERATED_ID = re.compile(r'(?:xdget[1-9][0-9]{0,14}|ltBlock[1-9][0-9]{0,14}|'
                          r'lite-block-live-wrapper-[1-9][0-9]{0,14}-[0-9]{1,8}|'
                          r'docs-internal-guid-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})')
INERT_IMAGE_CSS = {'box-sizing': {'border-box'}, 'border': {'0', '0px'},
                   'vertical-align': {'middle'}, 'max-width': {'100%'},
                   'margin-left': {'0', '0px'}, 'margin-top': {'0', '0px'}}


def _review(code='reviewed_getcourse_requires_review'):
    raise Review(code)


def _digest(value):
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _review('reviewed_getcourse_source_invalid')
    return hashlib.sha256(raw).hexdigest()


def _number(value):
    if type(value) is int and 0 < value <= 2**31 - 1: return value
    if isinstance(value, str) and re.fullmatch('[1-9][0-9]{0,9}', value) and int(value) <= 2**31 - 1: return int(value)


def _editor_attr(key, value):
    if not isinstance(value, str): return False
    if key in {'data-xdget-id', 'data-block-id', 'data-updated'}:
        return bool(re.fullmatch('[1-9][0-9]{0,14}', value))
    if key == 'data-code': return bool(re.fullmatch(r'(?:b-[0-9a-f]{5}|ltBlock[1-9][0-9]{0,14})', value))
    return value == {'data-editable': 'true', 'data-main-class': 'header', 'data-param': 'header'}.get(key)


class _Signature(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.images = [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append(('start', tag))
        if tag == 'img':
            values = dict(attrs)
            dimensions = []
            for part in values.get('style', '').split(';'):
                if ':' in part:
                    key, value = (v.strip() for v in part.split(':', 1))
                    if key.lower() in {'width', 'height'}: dimensions.append((key.lower(), value))
            self.images.append((tuple((k, values.get(k)) for k in ('src', 'alt', 'width', 'height')), dimensions))

    def handle_startendtag(self, tag, attrs): self.handle_starttag(tag, attrs)
    def handle_endtag(self, tag):
        if tag not in VOID: self.tags.append(('end', tag))


def _signature(source):
    parser = _Signature(); parser.feed(source); parser.close()
    return _material(source), parser.tags, parser.images


class _Wrappers(HTMLParser):
    def __init__(self, source, validate):
        super().__init__(convert_charrefs=False)
        self.source, self.validate = source, validate
        self.globals = getattr(validate, '__globals__', {})
        if any(not isinstance(self.globals.get(k), (set, frozenset)) for k in ('TAGS', 'CLASSES')):
            _review('reviewed_getcourse_validator_invalid')
        self.allowed = self.globals['TAGS'] - {'style', 'iframe'} | {'img'}
        self.lines = [0] + [i + 1 for i, c in enumerate(source) if c == '\n']
        self.stack, self.edits, self.removed_ids, self.references = [], [], set(), set()
        self.count = 0
        self.stats = {'editor_attributes': 0, 'generated_ids': 0, 'inert_classes': 0,
                      'centered_blocks': 0, 'image_presentation': 0}
        self.feed(source); self.close()
        if self.stack or self.removed_ids & self.references: _review()

    def position(self):
        line, column = self.getpos(); return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        self.count += 1
        if (self.count > 50000 or len(self.stack) > 100 or tag not in self.allowed
                or len(dict(attrs)) != len(attrs) or any(k.startswith('on') for k, _ in attrs)):
            _review()
        values, changed = dict(attrs), False
        if tag == 'a' and isinstance(values.get('href'), str):
            try: self.references.add(urlsplit(values['href']).fragment)
            except ValueError: _review()
        if 'id' in values:
            ident = values['id']
            if tag not in {'div', 'span'} or not isinstance(ident, str) or not GENERATED_ID.fullmatch(ident): _review()
            self.removed_ids.add(ident); values.pop('id'); changed = True
            self.stats['generated_ids'] += 1
        for key in list(values):
            if key in EDITOR_ATTRS:
                if tag != 'div' or not _editor_attr(key, values[key]): _review()
                values.pop(key); changed = True; self.stats['editor_attributes'] += 1
            elif key.startswith('data-'):
                _review()
        if 'class' in values:
            tokens = values['class'].split() if isinstance(values['class'], str) else []
            if not tokens or set(tokens) - self.globals['CLASSES'] - INERT_CLASSES - {'text-center'}: _review()
            kept = [v for v in tokens if v not in INERT_CLASSES and v != 'text-center']
            if len(kept) != len(tokens):
                if kept: values['class'] = ' '.join(kept)
                else: values.pop('class')
                self.stats['inert_classes'] += len(tokens) - len(kept); changed = True
            if 'text-center' in tokens:
                css = values.get('style', '')
                alignments = [p.split(':', 1)[1].strip().lower() for p in css.split(';')
                              if ':' in p and p.split(':', 1)[0].strip().lower() == 'text-align']
                if alignments and alignments != ['center']: _review()
                if not alignments: values['style'] = css + (';' if css and not css.rstrip().endswith(';') else '') + 'text-align:center'
                self.stats['centered_blocks'] += 1; changed = True
        if tag == 'img' and 'style' in values:
            if not isinstance(values['style'], str): _review()
            kept, seen = [], set()
            for part in values['style'].split(';'):
                if not part.strip(): continue
                if ':' not in part: _review()
                key, value = (v.strip() for v in part.split(':', 1)); key = key.lower()
                if key in seen: _review()
                seen.add(key)
                if key in INERT_IMAGE_CSS:
                    if value not in INERT_IMAGE_CSS[key]: _review()
                    self.stats['image_presentation'] += 1; changed = True
                else: kept.append(part)
            if kept: values['style'] = ';'.join(kept)
            else: values.pop('style')
        if changed:
            opening = '<' + tag + ''.join(' ' + k + ('="' + escape(v, quote=True) + '"' if v is not None else '')
                                         for k, v in values.items()) + '>'
            start = self.position(); self.edits.append((start, start + len(self.get_starttag_text()), opening))
        if tag not in VOID: self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID: return
        if not self.stack or self.stack.pop() != tag: _review()

    def handle_startendtag(self, tag, attrs):
        if tag not in VOID: _review()
        self.handle_starttag(tag, attrs)

    def handle_comment(self, data): _review()
    handle_decl = handle_comment
    handle_pi = handle_comment
    unknown_decl = handle_comment

    def rendered(self):
        result = self.source
        for start, end, opening in reversed(self.edits): result = result[:start] + opening + result[end:]
        return result


def _clean(source, validate):
    if not isinstance(source, str) or not 0 < len(source.encode()) <= 200000: _review()
    parser = _Wrappers(source, validate); cleaned = parser.rendered()
    wrapper_result = clean_image_wrappers(cleaned, validate)
    if wrapper_result:
        cleaned = wrapper_result[0]; parser.stats['image_wrappers'] = wrapper_result[1]
    try:
        document = Document(cleaned)
        validate(_probe(document.root))
    except (Review, ValueError, UnicodeError, RecursionError): _review()
    if _signature(source) != _signature(cleaned): _review('reviewed_getcourse_material_mismatch')
    return cleaned, parser.stats, len(document.images)


def normalize_reviewed_getcourse(ape, course_id, lesson_id, validate_static):
    """Use before editor/image passes; caller must retain original APE and witness.

    Exact configured source mismatches fail immediately. Unconfigured lessons
    are returned unchanged. This helper never changes source image URLs, issues
    network requests, drops conditions or creates imports/files.
    """
    if (ACCOUNT, ORIGIN) != ('mastervision', 'https://shop.mastervision.su'):
        _review('reviewed_getcourse_account_mismatch')
    if (not isinstance(ape, dict) or ape.get('name') != 'page'
            or not isinstance(ape.get('children'), list) or not callable(validate_static)):
        _review('reviewed_getcourse_source_invalid')
    context = (_number(course_id), _number(lesson_id))
    if None in context: _review('reviewed_getcourse_source_invalid')
    try: result = copy.deepcopy(ape)
    except (TypeError, RecursionError): _review('reviewed_getcourse_source_invalid')
    binding = BINDINGS.get(context)
    if binding is None: return result, []
    path, node_hash, html_hash = binding; node = result
    for index in path:
        fields, children = node.get('fields', {}), node.get('children')
        if (not isinstance(fields, dict) or fields.get('anchor') not in (None, '')
                or any(fields.get(k) not in (None, '') for k in ('visibleConditions', 'displayDelay'))
                or not isinstance(children, list) or not 0 <= index < len(children)):
            _review('reviewed_getcourse_source_changed')
        node = children[index]
        if not isinstance(node, dict): _review('reviewed_getcourse_source_changed')
    if _digest(node) != node_hash: _review('reviewed_getcourse_source_changed')
    fields = node.get('fields', {})
    if not isinstance(fields, dict): _review('reviewed_getcourse_source_invalid')
    source = fields.get('html')
    if (node.get('name') != 'text' or set(fields) - {'html', 'anchor'}
            or fields.get('anchor') not in (None, '') or node.get('children', []) != []
            or not isinstance(node.get('children', []), list)
            or set(node) - {'id', 'name', 'fields', 'style', 'children'} or _has_content_style(node.get('style'))
            or not isinstance(source, str) or hashlib.sha256(source.encode()).hexdigest() != html_hash):
        _review('reviewed_getcourse_requires_review')
    cleaned, stats, images = _clean(source, validate_static)
    fields['html'] = cleaned
    return result, [{'path': list(path), 'code': CODE, 'source_node_sha256': node_hash,
                     'html_sha256': html_hash, 'result_sha256': hashlib.sha256(cleaned.encode()).hexdigest(),
                     'images': images, **stats}]
