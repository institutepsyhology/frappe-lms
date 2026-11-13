"""Exact owner-approved media omissions; every other material stays unchanged."""
import copy
import hashlib
from html.parser import HTMLParser
import re

from importer import ACCOUNT, ORIGIN, Review
from normalize_editor_nodes import _style_content

CODE = 'owner_media_omitted'
GIF_SHA256 = '9d2b67e589360c6d8956b6ed18990bb99099b95925d4a232664ad96986ab1bfc'
MISSING_SHA256 = '20e470bd0c3f6cd94a7e69f47bd8389f10d98bedff8ea1681e3803794969ed86'
MISSING_TAG_SHA256 = '07c531238cd97d0808a28e3a4fa760f8a76845320793dc225359ae4713c56d38'
APPROVED = {(618, lid): {'path': (0, 0, 0), 'kind': 'animated_gif', 'src_sha256': GIF_SHA256}
            for lid in (6825, 6848, 6849, 6852)}
APPROVED[(520, 5223)] = {'path': (2,), 'kind': 'missing_404_image',
                        'src_sha256': MISSING_SHA256, 'tag_sha256': MISSING_TAG_SHA256}
NODE_KEYS = {'id', 'name', 'fields', 'children', 'style'}
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
PARENTS = {'p', 'div', 'span', 'strong', 'b', 'em', 'i', 'u', 's', 'li', 'ul', 'ol', 'blockquote'}


def _sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest() if isinstance(value, str) else None


def _at(ape, path):
    node, ancestors = ape, []
    for index in path:
        children = node.get('children', [])
        if index >= len(children): return None, []
        ancestors.append(node)
        node = children[index]
    return node, ancestors


def _protected(node):
    fields = node.get('fields', {})
    return (bool(set(node) - NODE_KEYS)
            or any(fields.get(key) is not None for key in ('visibleConditions', 'displayDelay'))
            or any(fields.get(key) not in (None, '') for key in ('anchor', 'linkHref', 'event', 'toAnchor')))


def _gif(node, ancestors, policy):
    fields = node.get('fields', {})
    return (node.get('name') == 'image' and not node.get('children')
            and isinstance(node.get('id'), str) and re.fullmatch('[A-Za-z0-9_-]{1,80}', node['id'])
            and set(fields) <= {'anchor', 'displayDelay', 'imageSrc', 'linkHref', 'visibleConditions'}
            and _sha(fields.get('imageSrc')) == policy['src_sha256']
            and not _protected(node) and not _style_content(node.get('style'))
            and [parent['name'] for parent in ancestors] == ['page', 'section', 'column']
            and all(not _protected(parent) for parent in ancestors))


class _Material(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.links, self.images = [], [], []

    def handle_data(self, data): self.text.append(data)
    def handle_starttag(self, tag, attrs):
        if tag == 'a': self.links.append(tuple(attrs))
        if tag == 'img': self.images.append(tuple(attrs))
    def handle_startendtag(self, tag, attrs): self.handle_starttag(tag, attrs)
    def signature(self): return ''.join(self.text), tuple(self.links), tuple(self.images)


class _ApprovedTag(_Material):
    def __init__(self, source, policy):
        super().__init__()
        self.source, self.policy, self.stack, self.matches = source, policy, [], []
        self.lines = [0] + [i + 1 for i, char in enumerate(source) if char == '\n']

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'img' and _sha(values.get('src')) == self.policy['src_sha256']:
            raw = self.get_starttag_text()
            safe = (len(values) == len(attrs) and set(values) == {'src', 'width', 'height'}
                    and all(isinstance(values.get(key), str) and re.fullmatch('[1-9][0-9]{0,4}', values[key])
                            for key in ('width', 'height'))
                    and _sha(raw) == self.policy['tag_sha256']
                    and all(not protected for name, protected in self.stack))
            if not safe: raise ValueError('approved_image_changed')
            line, column = self.getpos()
            start = self.lines[line - 1] + column
            self.matches.append((start, start + len(raw)))
        else:
            super().handle_starttag(tag, attrs)
        if tag not in VOID:
            protected = (tag not in PARENTS or any(key.lower().startswith('on')
                or key.lower() in {'href', 'action', 'data-action', 'src', 'formaction'}
                or any(part in key.lower() for part in ('condition', 'permission', 'access', 'delay'))
                for key, value in attrs))
            self.stack.append((tag, protected))

    def handle_startendtag(self, tag, attrs):
        before = len(self.stack)
        self.handle_starttag(tag, attrs)
        del self.stack[before:]

    def handle_endtag(self, tag):
        if tag in VOID: return
        if not self.stack or self.stack[-1][0] != tag: raise ValueError('approved_image_markup_changed')
        self.stack.pop()


def _inline(node, ancestors, policy):
    fields = node.get('fields', {})
    source = fields.get('html')
    if (node.get('name') != 'text' or node.get('children') or set(fields) - {'anchor', 'html'}
            or _protected(node) or any(_protected(parent) for parent in ancestors)
            or not isinstance(source, str)):
        return None
    try:
        if len(source.encode('utf-8')) > 200000: return None
        before = _ApprovedTag(source, policy)
        before.feed(source)
        before.close()
        if before.stack or len(before.matches) != 1: return None
        start, end = before.matches[0]
        cleaned = source[:start] + source[end:]
        after = _Material()
        after.feed(cleaned)
        after.close()
        if before.signature() != after.signature(): return None
    except (ValueError, UnicodeError, RecursionError):
        return None
    return cleaned


def normalize_owner_media_omissions(ape, course_id, lesson_id):
    """Return a copy and exact-path witnesses for five approved source bindings.

    GIF omissions never include the nearby PNGs. The single HTML image is
    removed by exact original tag range; text, captions, links and other images
    must remain unchanged. Unknown or edited candidates stay for review.
    """
    if (ACCOUNT, ORIGIN) != ('mastervision', 'https://shop.mastervision.su'):
        raise Review('owner_media_account_mismatch')
    if not isinstance(ape, dict) or ape.get('name') != 'page' or not isinstance(ape.get('children'), list):
        raise Review('owner_media_ape_invalid')
    copied = copy.deepcopy(ape)
    pending, visited = [(copied, 0)], 0
    while pending:
        node, depth = pending.pop(); visited += 1
        if (visited > 150000 or depth > 100 or not isinstance(node, dict) or not isinstance(node.get('name'), str)
                or not isinstance(node.get('fields', {}), dict) or not isinstance(node.get('children', []), list)):
            raise Review('owner_media_ape_invalid')
        pending.extend((child, depth + 1) for child in node.get('children', []))
    policy = APPROVED.get((course_id, lesson_id)) if type(course_id) is int and type(lesson_id) is int else None
    if policy is None: return copied, []
    path = policy['path']
    node, ancestors = _at(copied, path)
    if node is None: return copied, []
    if policy['kind'] == 'animated_gif':
        # A new duplicate is a changed source, not another approved omission.
        same_source = 0
        pending = [copied]
        while pending:
            item = pending.pop()
            if item['name'] == 'image' and _sha(item.get('fields', {}).get('imageSrc')) == policy['src_sha256']:
                same_source += 1
            pending.extend(item.get('children', []))
        if same_source != 1: return copied, []
        if not _gif(node, ancestors, policy): return copied, []
        ancestors[-1]['children'].pop(path[-1])
    else:
        cleaned = _inline(node, ancestors, policy)
        if cleaned is None: return copied, []
        node['fields']['html'] = cleaned
    change = {'path': list(path), 'code': CODE, 'kind': policy['kind'], 'src_sha256': policy['src_sha256']}
    if 'tag_sha256' in policy: change['tag_sha256'] = policy['tag_sha256']
    return copied, [change]
