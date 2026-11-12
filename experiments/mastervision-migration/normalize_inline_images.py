"""Split conservative static HTML into balanced text and native image blocks.

The caller retains the complete original APE. Image sizing is validated but is
not reconstructed by the current native renderer; metadata records its count.
This module never downloads a URL or executes source HTML.
"""
import base64
import binascii
import copy
import hashlib
from html.parser import HTMLParser
import json
import re
from urllib.parse import urlsplit

from importer import Review

CODE = 'inline_html_images_normalized'
MAX_HTML = 16 * 1024 * 1024
MAX_IMAGE = 5 * 1024 * 1024
EDITOR_ATTRS = {'data-main-class','data-param','data-image-editable','data-hash'}
VOID = {'img','br','hr','col'}
FORBIDDEN_ANCESTORS = {'a','table','thead','tbody','tfoot','tr','td','th','ul','ol','li','dl','dt','dd',
                       'iframe','script','style','form','textarea','select','button','object','embed','audio','video','picture','svg','math'}


def _source(value):
    if not isinstance(value, str) or not value: raise Review('inline_image_source_invalid')
    if value.startswith('data:'):
        match = re.fullmatch(r'data:image/(png|jpeg|jpg|webp);base64,([A-Za-z0-9+/]*={0,2})', value)
        if not match or len(match[2]) > ((MAX_IMAGE + 2) // 3) * 4: raise Review('inline_image_source_invalid')
        try: raw = base64.b64decode(match[2], validate=True)
        except (ValueError, binascii.Error): raise Review('inline_image_source_invalid') from None
        if not raw or len(raw) > MAX_IMAGE or base64.b64encode(raw).decode() != match[2]: raise Review('inline_image_source_invalid')
        return value
    if re.search(r'[\x00-\x20\x7f\\]', value): raise Review('inline_image_source_invalid')
    try:
        url = urlsplit(value)
        if url.scheme not in ('https','http') or not url.hostname or url.username is not None or url.password is not None or url.port is not None or url.fragment:
            raise ValueError()
    except ValueError: raise Review('inline_image_source_invalid') from None
    return value


def _size(value):
    return isinstance(value, str) and bool(re.fullmatch('[1-9][0-9]{0,3}', value)) and int(value) <= 4096


def _style(value):
    if not isinstance(value, str) or len(value) > 200: return False
    seen = set()
    for piece in value.split(';'):
        if not piece.strip(): continue
        if ':' not in piece: return False
        key, dimension = (part.strip().lower() for part in piece.split(':',1))
        if key not in ('width','height') or key in seen: return False
        seen.add(key)
        if dimension == 'auto': continue
        match = re.fullmatch(r'([0-9]+(?:\.[0-9]{1,3})?)(px|%)', dimension)
        if not match or not 0 < float(match[1]) <= (4096 if match[2] == 'px' else 100): return False
    return True


class Element:
    def __init__(self, tag='', attrs=(), opening=''):
        self.tag, self.attrs, self.opening = tag, dict(attrs), opening
        self.closing, self.children = '', []


class Document(HTMLParser):
    def __init__(self, markup):
        super().__init__(convert_charrefs=False)
        self.markup = markup; self.lines = [0] + [index + 1 for index,char in enumerate(markup) if char == '\n']
        self.root = Element(); self.stack = [self.root]; self.images = []; self.count = 0
        self.feed(markup); self.close()
        if len(self.stack) != 1: raise Review('inline_image_malformed_html')

    def position(self):
        row, column = self.getpos(); return self.lines[row - 1] + column

    def handle_starttag(self, tag, attrs):
        self.count += 1
        if self.count > 50000 or len(self.stack) > 100 or len(dict(attrs)) != len(attrs): raise Review('inline_image_malformed_html')
        node = Element(tag, attrs, self.get_starttag_text()); self.stack[-1].children.append(node)
        if tag == 'img':
            if any(ancestor.tag in FORBIDDEN_ANCESTORS or 'id' in ancestor.attrs for ancestor in self.stack):
                raise Review('inline_image_context_requires_review')
            extra = set(node.attrs) - {'src','alt','width','height','style'}
            if extra and (extra != EDITOR_ATTRS or node.attrs.get('data-main-class') != 'lt-image-common'
                    or node.attrs.get('data-param') != 'image' or node.attrs.get('data-image-editable') != 'true'
                    or not isinstance(node.attrs.get('data-hash'),str)
                    or not re.fullmatch(r'[a-fA-F0-9]{32}\.(?:jpg|png)',node.attrs['data-hash'])):
                raise Review('inline_image_attributes_require_review')
            alt = node.attrs.get('alt')
            if alt is not None and (not isinstance(alt, str) or alt.strip()): raise Review('inline_image_caption_requires_review')
            if any(not _size(node.attrs[key]) for key in ('width','height') if key in node.attrs): raise Review('inline_image_dimensions_require_review')
            if 'style' in node.attrs and not _style(node.attrs['style']): raise Review('inline_image_dimensions_require_review')
            _source(node.attrs.get('src')); self.images.append(node)
        if tag not in VOID: self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        if tag not in VOID: raise Review('inline_image_malformed_html')
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in VOID or len(self.stack) == 1 or self.stack[-1].tag != tag: raise Review('inline_image_malformed_html')
        start = self.position(); end = self.markup.find('>', start)
        if end < 0: raise Review('inline_image_malformed_html')
        self.stack.pop().closing = self.markup[start:end + 1]

    def handle_data(self, value): self.stack[-1].children.append(value)
    def handle_entityref(self, name): self.handle_data('&' + name + ';')
    def handle_charref(self, name): self.handle_data('&#' + name + ';')
    def handle_comment(self, value): raise Review('inline_image_malformed_html')
    def handle_decl(self, value): raise Review('inline_image_malformed_html')
    def handle_pi(self, value): raise Review('inline_image_malformed_html')


def _parts(document, validate):
    result, buffer, ancestors = [], [], []
    meaningful = False
    def flush():
        nonlocal buffer, meaningful
        if meaningful:
            fragment = ''.join(buffer) + ''.join(node.closing for node in reversed(ancestors))
            try: validate(fragment)
            except (ValueError, UnicodeError, RecursionError): raise Review('inline_image_html_requires_review') from None
            result.append(('text', fragment))
        buffer = [node.opening for node in ancestors]; meaningful = False
    def visit(node):
        nonlocal meaningful
        if isinstance(node, str):
            buffer.append(node)
            if node: meaningful = True
        elif node.tag == 'img':
            flush(); result.append(('image', node))
        else:
            buffer.append(node.opening)
            if node.tag in ('br','hr','a','table','iframe','ul','ol'): meaningful = True
            if node.tag not in VOID: ancestors.append(node)
            for child in node.children: visit(child)
            if node.tag not in VOID:
                ancestors.pop(); buffer.append(node.closing)
    for node in document.root.children: visit(node)
    flush()
    return result


class Content(HTMLParser):
    def __init__(self): super().__init__(convert_charrefs=False); self.text = []; self.links = []; self.images = []
    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'a': self.links.append(values.get('href'))
        if tag == 'img': self.images.append(values.get('src'))
    def handle_data(self, value): self.text.append(value)
    def handle_entityref(self, name): self.text.append('&' + name + ';')
    def handle_charref(self, name): self.text.append('&#' + name + ';')


def _probe(node):
    if isinstance(node, str): return node
    if node.tag == 'img': return '<span></span>'
    return node.opening + ''.join(_probe(child) for child in node.children) + node.closing


def normalize_inline_images(ape, validate_static):
    """Return copied APE and metadata-only transformations using original paths."""
    if not callable(validate_static): raise Review('inline_image_validator_invalid')
    if not isinstance(ape, dict) or ape.get('name') != 'page' or not isinstance(ape.get('children'), list): raise Review('inline_image_source_invalid')
    copied = copy.deepcopy(ape); occupied = set(); pending = [(copied,0)]; changes = []; node_count = 0
    while pending:
        node,depth = pending.pop(); node_count += 1
        if depth > 100 or node_count > 150000 or not isinstance(node, dict) or not isinstance(node.get('children',[]),list): raise Review('inline_image_source_invalid')
        if isinstance(node.get('id'),str): occupied.add(node['id'])
        pending.extend((child,depth + 1) for child in node.get('children',[]))
    def new_id(kind, path, markup, ordinal):
        digest = hashlib.sha256(json.dumps([path,markup,kind,ordinal],ensure_ascii=True,separators=(',',':')).encode()).hexdigest()
        ident = ('mvi_' if kind == 'image' else 'mvt_') + digest[:48]
        if ident in occupied: raise Review('inline_image_id_collision')
        occupied.add(ident); return ident
    def split(node,path):
        fields = node.get('fields',{}); markup = fields.get('html') if isinstance(fields,dict) else None
        if node.get('name') not in ('text','code','header') or not isinstance(markup,str) or not re.search(r'<\s*img\b',markup,re.I): return [node]
        header = node['name'] == 'header'
        allowed = {'html','anchor','format'} if header else {'html','anchor'}
        if (node.get('children') or set(fields) - allowed or fields.get('anchor') not in (None,'') or len(markup) > MAX_HTML
                or set(node) - {'id','name','fields','children','style'}
                or header and fields.get('format') not in ('h1','h2','h3','h4','h5','h6')):
            raise Review('inline_image_node_requires_review')
        document = Document(markup)
        if not document.images: raise Review('inline_image_source_invalid')
        if header:
            pending = [document.root]; heading_found = False
            while pending:
                item = pending.pop()
                if isinstance(item,Element):
                    heading_found |= bool(re.fullmatch('h[1-6]',item.tag)); pending.extend(item.children)
            if not heading_found: raise Review('inline_image_node_requires_review')
        # Even an image-only wrapper must be checked before an empty wrapper
        # can disappear during splitting. Keep every original tag/attribute in
        # this probe, replacing only already-validated images with inert spans.
        try: validate_static(_probe(document.root))
        except (ValueError, UnicodeError, RecursionError): raise Review('inline_image_html_requires_review') from None
        parts = _parts(document,validate_static); result = []; first_text = True
        before, after = Content(), Content(); before.feed(markup)
        image_sources = []
        for ordinal,(kind,value) in enumerate(parts):
            if kind == 'image':
                source = value.attrs['src']; image_sources.append(source)
                result.append({'id':new_id('image',path,markup,ordinal),'name':'image',
                    'fields':{'anchor':'','imageSrc':source},'children':[]})
            else:
                clone = copy.deepcopy(node); clone['name'] = 'text'; clone['fields']['html'] = value
                if header: clone['fields'].pop('format')
                if not first_text: clone['id'] = new_id('text',path,markup,ordinal)
                first_text = False; result.append(clone); after.feed(value)
        if ''.join(before.text) != ''.join(after.text) or before.links != after.links or before.images != image_sources:
            raise Review('inline_image_content_mismatch')
        metadata = {'path':list(path),'code':CODE,'images':len(document.images),
                    'sized_images':sum(any(key in image.attrs for key in ('width','height','style')) for image in document.images)}
        editor_images = sum(EDITOR_ATTRS.issubset(image.attrs) for image in document.images)
        if editor_images: metadata['editor_metadata_images'] = editor_images
        changes.append(metadata)
        return result
    def walk(node,path):
        if len(path) > 100: raise Review('inline_image_source_invalid')
        if 'children' in node:
            children = []
            for index,child in enumerate(node['children']): children.extend(walk(child,path + [index]))
            node['children'] = children
        return split(node,path)
    return walk(copied,[])[0], changes
