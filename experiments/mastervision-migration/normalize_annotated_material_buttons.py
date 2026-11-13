"""Preserve two owner-reviewed annotated link fields as static lesson material."""
import copy
import hashlib
from html import escape
from html.parser import HTMLParser
import re
from urllib.parse import parse_qsl, urlsplit

from importer import ACCOUNT, ORIGIN, Review
from normalize_editor_nodes import _core, _style_content

CODE = 'annotated_material_button_html_preserved'
SCOPES = {(326, 5253), (525, 5302)}
BASE_FIELDS = {'anchor', 'html', 'icon', 'linkType', 'url', 'blank', 'toAnchor', 'event'}
NULL_FIELDS = {'visibleConditions', 'displayDelay'}
INLINE = {'span', 'b', 'strong', 'i', 'em', 'u', 's', 'sub', 'sup', 'mark', 'br'}
ANNOTATION = '  Презентация: '
PREFIX = 'ко 2 видео '


class _Content(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ok, self.parts, self.links = True, [], []
    def handle_starttag(self, tag, attrs):
        if tag not in INLINE: self.ok = False
        if tag == 'a': self.links.append(dict(attrs).get('href'))
    def handle_startendtag(self, tag, attrs): self.handle_starttag(tag, attrs)
    def handle_endtag(self, tag):
        if tag not in INLINE: self.ok = False
    def handle_data(self, data): self.parts.append(data)
    def handle_comment(self, data): self.ok = False
    def handle_decl(self, data): self.ok = False
    def handle_pi(self, data): self.ok = False


def _url(value, kind):
    if not isinstance(value, str) or not _core()._url(value): return False
    try:
        url = urlsplit(value)
        if (url.scheme != 'https' or url.username is not None or url.password is not None
                or url.port is not None or url.fragment): return False
        if kind == 'yandex':
            return (url.hostname == 'disk.yandex.ru' and not url.query and
                    bool(re.fullmatch(r'/(?:d|i)/[A-Za-z0-9_-]{1,200}', url.path)))
        query = parse_qsl(url.query, keep_blank_values=True, strict_parsing=True)
        return (url.hostname == 'drive.google.com' and
                bool(re.fullmatch(r'/file/d/[A-Za-z0-9_-]{1,200}/view', url.path)) and
                query in ([], [('usp', 'sharing')]))
    except ValueError: return False


def _markup(node, scope, validate):
    fields = node.get('fields', {})
    if (node.get('children', []) or set(node) - {'id', 'name', 'fields', 'children', 'style'}
            or not BASE_FIELDS <= set(fields) or set(fields) - BASE_FIELDS - NULL_FIELDS
            or any(fields[key] is not None for key in NULL_FIELDS if key in fields)
            or fields.get('linkType') != 'url' or type(fields.get('blank')) is not bool
            or any(fields.get(key) not in (None, '', False) for key in ('anchor', 'icon', 'toAnchor', 'event'))
            or _style_content(node.get('style'))): return None
    label, source = fields.get('html'), fields.get('url')
    if (not isinstance(label, str) or not label or len(label) > 10000
            or not isinstance(source, str) or len(source) > 20000): return None
    parsed = _Content()
    try:
        parsed.feed(label); parsed.close()
        if not parsed.ok or ' '.join(''.join(parsed.parts).split()).upper() != 'АУДИОЗАПИСЬ': return None
        validate('<p>' + label + '</p>')
    except (ValueError, UnicodeError, RecursionError): return None
    window = ' target="_blank" rel="noopener noreferrer"' if fields['blank'] else ''
    if scope == (326, 5253):
        parts = source.split(ANNOTATION)
        if len(parts) != 2 or not all(_url(value, 'yandex') for value in parts): return None
        urls, form = parts, 'two_material_links'
        markup = ('<p><a href="' + escape(urls[0], quote=True) + '"' + window + '>' + label +
                  '</a><a href="' + escape(urls[1], quote=True) + '"' + window + '>' + escape(ANNOTATION) + '</a></p>')
        expected_text = ''.join(parsed.parts) + ANNOTATION
    else:
        if not source.startswith(PREFIX): return None
        value = source[len(PREFIX):]
        if not _url(value, 'drive'): return None
        urls, form = [value], 'video_material_note'
        markup = ('<p>' + escape(PREFIX) + '<a href="' + escape(value, quote=True) + '"' + window +
                  '>' + label + '</a></p>')
        expected_text = PREFIX + ''.join(parsed.parts)
    try: validate(markup)
    except (ValueError, UnicodeError, RecursionError): return None
    content = _Content(); content.feed(markup); content.close()
    if content.links != urls or ''.join(content.parts) != expected_text:
        raise Review('annotated_material_button_material_mismatch')
    return markup, {'form': form, 'links': len(urls), 'source_url_sha256': hashlib.sha256(source.encode()).hexdigest()}


def normalize_annotated_material_buttons(ape, validate_static, course_id, lesson_id):
    """Return copied APE and URL-free metadata; caller retains the original APE.

    Only explicit source URLs and their exact labels/notes are rendered. Other
    buttons, including duplicate neighbouring material links, remain unchanged.
    """
    if (ACCOUNT, ORIGIN) != ('mastervision', 'https://shop.mastervision.su'):
        raise Review('normalization_account_mismatch')
    if type(course_id) is not int or course_id <= 0 or type(lesson_id) is not int or lesson_id <= 0:
        raise Review('annotated_material_button_identity_invalid')
    if not callable(validate_static): raise Review('annotated_material_button_validator_invalid')
    if not isinstance(ape, dict) or ape.get('name') != 'page' or not isinstance(ape.get('children'), list):
        raise Review('annotated_material_buttons_invalid')
    copied, changes, visited = copy.deepcopy(ape), [], 0
    scope = (course_id, lesson_id)
    if scope not in SCOPES: return copied, changes

    def walk(node, path, protected=False):
        nonlocal visited
        visited += 1
        if visited > 150000 or len(path) > 100 or not isinstance(node, dict) or not isinstance(node.get('name'), str):
            raise Review('annotated_material_buttons_invalid')
        fields, children = node.get('fields', {}), node.get('children', [])
        if not isinstance(fields, dict) or not isinstance(children, list): raise Review('annotated_material_buttons_invalid')
        protected = protected or any(fields.get(key) not in (None, '', False, [], {})
                                     for key in NULL_FIELDS)
        if node['name'] == 'button' and not protected:
            result = _markup(node, scope, validate_static)
            if result is not None:
                if changes: raise Review('annotated_material_button_ambiguous')
                markup, metadata = result
                node['name'], node['fields'] = 'text', {'html': markup}
                changes.append({'path': list(path), 'code': CODE, **metadata})
        for index, child in enumerate(children): walk(child, path + [index], protected)

    walk(copied, [])
    return copied, changes
