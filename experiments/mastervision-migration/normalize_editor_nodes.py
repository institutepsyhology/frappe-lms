"""Conservative native editor metadata repairs; original APE stays with caller."""
import copy
from functools import lru_cache
from html import unescape
from html.parser import HTMLParser
import importlib.util
from pathlib import Path
import re
import sys

from importer import Review
from avatar_placeholders import is_known_avatar_url


@lru_cache(maxsize=1)
def _core():
    """Load trusted pure converter validators, never evaluate source-page code."""
    repo = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location('mastervision_editor_core', repo / 'lms/lms/avo_transform.py')
    module = importlib.util.module_from_spec(spec)
    inserted = str(repo) not in sys.path
    if inserted: sys.path.insert(0, str(repo))
    try: spec.loader.exec_module(module)
    finally:
        if inserted: sys.path.remove(str(repo))
    return module


def _empty(value):
    return value in (None, '', False, [], {})


class _Heading(HTMLParser):
    def __init__(self): super().__init__(); self.found = False
    def handle_starttag(self, tag, attrs):
        if re.fullmatch('h[1-6]', tag): self.found = True


class _DefaultLabel(HTMLParser):
    def __init__(self): super().__init__(); self.ok = True; self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag not in ('p','br','span','b','strong','i','em') or attrs: self.ok = False
    def handle_data(self, data): self.parts.append(data)
    def handle_comment(self, data): self.ok = False


def _caption_empty(value, validate):
    if value in (None, ''): return True
    if not isinstance(value, str): return False
    if '<' not in value: return value.strip() in ('', 'Видео')
    try: validate(value)
    except (ValueError, UnicodeError, RecursionError): return False
    label = _DefaultLabel(); label.feed(value); label.close()
    return label.ok and ''.join(label.parts).strip() in ('', 'Видео')


def _style_content(value, depth=0, path=()):
    if depth > 100: return True
    if isinstance(value, dict):
        # AVO's list-style group calls its formatting control "content". It is
        # not a lesson caption; media/markup inside it is still checked below.
        return any((str(key).lower() in ('content','html','text','caption','title','label')
                    and not (path == ('lists',) and key == 'content') and not _empty(child))
                   or _style_content(child, depth + 1, path + (key,)) for key, child in value.items())
    if isinstance(value, list): return any(_style_content(child, depth + 1, path + (index,)) for index, child in enumerate(value))
    return isinstance(value, str) and bool(re.search(r'https?:|data:|url\s*\(|<', value, re.I))


def _empty_video(node, validate):
    fields = node['fields']
    media = {'videoSrc','videoSrc2','embeddedHtml','posterSrc','posterSrc2','anchor'}
    providers = {'videoProvider','videoProvider2'}
    flags = {'nativePlayer','nativePlayer2','isShowProgressControl','isShowProgressControl2',
             'isShowFastRewindButtons','isShowFastRewindButtons2','isFloating'}
    if set(fields) - media - providers - flags - {'html'}: return False
    if node.get('children', []) or any(fields.get(key) not in (None, '') for key in media): return False
    if any(fields.get(key) not in (None, '', 'youtube', 'rutube') for key in providers): return False
    if any(fields.get(key) not in (None, '', False, True, 0, 1, '0', '1') for key in flags): return False
    if not _caption_empty(fields.get('html'), validate) or _style_content(node.get('style')): return False
    return all(_empty(value) for key, value in node.items() if key not in ('id','name','fields','children','style'))


def _personalized_avatar(node):
    fields = node['fields']
    return (not set(fields) - {'anchor', 'imageSrc', 'linkHref'}
            and (fields.get('imageSrc') == '{avatar_url}' or is_known_avatar_url(fields.get('imageSrc')))
            and fields.get('anchor') in (None, '') and fields.get('linkHref') in (None, '')
            and not node.get('children', [])
            and not set(node) - {'id', 'name', 'fields', 'children', 'style'}
            and not _style_content(node.get('style')))


def _header_as_text(node, validate):
    fields = node['fields']; markup = fields.get('html')
    if (set(fields) - {'anchor','format','html'} or fields.get('anchor') not in (None, '')
            or node.get('children', []) or not isinstance(markup, str) or not markup.strip()): return False
    probe = _Heading(); probe.feed(markup); probe.close()
    if not probe.found: return False
    try: validate(markup)
    except (ValueError, UnicodeError, RecursionError): return False
    # A single existing valid native heading already has a stable import
    # fingerprint, including the converter's supported format-mismatch warning.
    match = re.fullmatch(r'\s*<h([1-6])>(.*?)</h\1>\s*', markup, re.I | re.S)
    if (fields.get('format') in ('h1','h2','h3','h4','h5','h6') and match
            and _core()._safe_heading_inline(match.group(2))): return False
    return True


class _InlineBreaks(HTMLParser):
    def __init__(self, markup):
        super().__init__(convert_charrefs=False)
        self.lines = [0] + [i + 1 for i, char in enumerate(markup) if char == '\n']
        self.ranges, self.parts, self.ok = [], [], True
        self.feed(markup); self.close()

    def handle_starttag(self, tag, attrs):
        if tag == 'br':
            if attrs: self.ok = False
            line, column = self.getpos(); start = self.lines[line - 1] + column
            self.ranges.append((start, start + len(self.get_starttag_text())))

    def handle_startendtag(self, tag, attrs): self.handle_starttag(tag, attrs)
    def handle_endtag(self, tag):
        if tag == 'br': self.ok = False
    def handle_data(self, data): self.parts.append(data)
    def handle_entityref(self, name): self.parts.append(unescape('&' + name + ';'))
    def handle_charref(self, name): self.parts.append(unescape('&#' + name + ';'))


def _simple_header_markup(node, validate):
    fields = node['fields']; markup, level = fields.get('html'), fields.get('level')
    if (set(fields) != {'anchor', 'html', 'level'} or fields['anchor'] not in (None, '')
            or level not in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6') or node.get('children', [])
            or set(node) - {'id', 'name', 'fields', 'children', 'style'}
            or _style_content(node.get('style')) or not isinstance(markup, str)
            or not markup.strip() or len(markup) > 200000): return None
    try:
        validate(markup)
        probe = _InlineBreaks(markup)
        if not probe.ok or not probe.ranges or not ''.join(probe.parts).strip(): return None
        inline = markup
        for start, end in reversed(probe.ranges): inline = inline[:start] + inline[end:]
        if not _core()._safe_heading_inline(inline): return None
        wrapped = '<' + level + '>' + markup + '</' + level + '>'
        validate(wrapped)
    except (ValueError, UnicodeError, RecursionError): return None
    return wrapped


def normalize_nodes(ape, static_validator):
    """Return copied APE and ordered {path,code} repairs, with original paths.

    Valid source URLs and HTML are preserved exactly. Invalid/unknown media and
    meaningful settings stay untouched for the existing converter's review.
    """
    if not callable(static_validator): raise Review('editor_nodes_validator_invalid')
    if not isinstance(ape, dict) or ape.get('name') != 'page' or not isinstance(ape.get('children'), list):
        raise Review('editor_nodes_invalid')
    copied = copy.deepcopy(ape); changes = []; visited = 0
    def walk(node, path, protected=False):
        nonlocal visited
        visited += 1
        if visited > 150000 or len(path) > 100 or not isinstance(node, dict) or not isinstance(node.get('name'), str):
            raise Review('editor_nodes_invalid')
        fields, children = node.get('fields', {}), node.get('children', [])
        if not isinstance(fields, dict) or not isinstance(children, list): raise Review('editor_nodes_invalid')
        protected = protected or any(fields.get(key) not in (None, '', False, [], {})
                                     for key in ('visibleConditions', 'displayDelay'))
        # Missing fields is legitimate on structural nodes; do not insert an
        # empty dictionary because that would change an existing fingerprint.
        if node['name'] == 'image' and 'fields' in node and _personalized_avatar(node):
            changes.append({'path': list(path), 'code': 'personalized_avatar_placeholder_omitted'})
            return None
        if node['name'] == 'video' and 'fields' in node:
            corrected = False
            for suffix in ('', '2'):
                source, key = fields.get('videoSrc' + suffix), 'videoProvider' + suffix
                provider = next((provider for provider in ('youtube','rutube') if _core()._player_url(source, provider)), None)
                if provider is not None and fields.get(key) != provider:
                    fields[key] = provider; corrected = True
            if corrected: changes.append({'path': list(path), 'code': 'native_video_provider_normalized'})
            if _empty_video(node, static_validator):
                changes.append({'path': list(path), 'code': 'empty_video_block_omitted'})
                return None
        if node['name'] == 'header' and 'fields' in node and _header_as_text(node, static_validator):
            node['name'] = 'text'
            if 'format' in fields: del fields['format']
            changes.append({'path': list(path), 'code': 'header_markup_preserved_as_text'})
        if node['name'] == 'header-simple' and 'fields' in node and not protected:
            wrapped = _simple_header_markup(node, static_validator)
            if wrapped is not None:
                node['name'] = 'text'; fields['html'] = wrapped; del fields['level']
                changes.append({'path': list(path), 'code': 'simple_header_linebreak_html_preserved'})
        if 'children' in node:
            kept = []
            for index, child in enumerate(children):
                result = walk(child, path + [index], protected)
                if result is not None: kept.append(result)
            node['children'] = kept
        return node
    result = walk(copied, [])
    return result, changes
