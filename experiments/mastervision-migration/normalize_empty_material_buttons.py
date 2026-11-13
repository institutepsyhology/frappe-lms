"""Omit approved nonfunctional material buttons; caller retains original APE."""
import copy
from html.parser import HTMLParser

from importer import Review
from normalize_editor_nodes import _style_content


CODE = 'empty_material_button_omitted'
FIELDS = {'anchor', 'html', 'icon', 'linkType', 'url', 'blank', 'toAnchor', 'event'}
LABELS = {'АУДИОЗАПИСЬ', 'МАТЕРИАЛЫ'}
OWNER_APPROVED = {(329,4112), (435,4083), (446,4099), (485,4654), (487,4677),
                  (494,4716), (577,6192), (584,6310)} | {(618,lid) for lid in range(6929,6939)}
INLINE = {'span', 'b', 'strong', 'i', 'em', 'u', 's', 'sub', 'sup', 'mark', 'br'}


class _Label(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ok, self.parts = True, []

    def handle_starttag(self, tag, attrs):
        if tag not in INLINE: self.ok = False

    def handle_startendtag(self, tag, attrs): self.handle_starttag(tag, attrs)
    def handle_endtag(self, tag):
        if tag not in INLINE: self.ok = False
    def handle_data(self, data): self.parts.append(data)
    def handle_comment(self, data): self.ok = False
    def handle_decl(self, decl): self.ok = False
    def handle_pi(self, data): self.ok = False
    def unknown_decl(self, data): self.ok = False


def _empty_material(node, validate, owner_approved=False):
    fields = node.get('fields', {})
    if (set(node) - {'id', 'name', 'fields', 'children', 'style'}
            or node.get('children') or set(fields) - FIELDS
            or fields.get('linkType') != 'url' or fields.get('url') not in (None, '')
            or any(fields.get(key) not in (None, '', False) for key in ('anchor', 'icon', 'toAnchor', 'event'))
            or _style_content(node.get('style'))):
        return False
    blank, label = fields.get('blank'), fields.get('html')
    if (not (blank is None or blank == '' or type(blank) in (bool, int) and blank in (0, 1))
            or not isinstance(label, str) or not label or len(label) > 10000):
        return False
    try:
        parsed = _Label()
        parsed.feed(label)
        parsed.close()
        label_text = ' '.join(''.join(parsed.parts).split()).upper()
        if not parsed.ok or not label_text or not owner_approved and label_text not in LABELS:
            return False
        validate('<p>' + label + '</p>')
    except (ValueError, UnicodeError, RecursionError):
        return False
    return True


def normalize_empty_material_buttons(ape, validate_static, *, course_id=None, lesson_id=None):
    """Return a copied tree and original-path diagnostics, never inventing URLs.

    Known audio/material labels and the owner's exact additional lesson bindings
    qualify only with truly absent URLs and no other actions. Other lessons,
    meaningful settings and missing educational content remain for review.
    """
    if not callable(validate_static): raise Review('empty_material_buttons_validator_invalid')
    if not isinstance(ape, dict) or ape.get('name') != 'page' or not isinstance(ape.get('children'), list):
        raise Review('empty_material_buttons_invalid')
    copied, changes, visited = copy.deepcopy(ape), [], 0
    owner_approved = (type(course_id) is int and type(lesson_id) is int
                      and (course_id,lesson_id) in OWNER_APPROVED)

    def walk(node, path):
        nonlocal visited
        visited += 1
        if visited > 150000 or len(path) > 100 or not isinstance(node, dict) or not isinstance(node.get('name'), str):
            raise Review('empty_material_buttons_invalid')
        fields, children = node.get('fields', {}), node.get('children', [])
        if not isinstance(fields, dict) or not isinstance(children, list):
            raise Review('empty_material_buttons_invalid')
        if node['name'] == 'button' and _empty_material(node, validate_static, owner_approved):
            changes.append({'path': list(path), 'code': CODE})
            return None
        if 'children' in node:
            node['children'] = [kept for index, child in enumerate(children)
                                if (kept := walk(child, path + [index])) is not None]
        return node

    return walk(copied, []), changes
