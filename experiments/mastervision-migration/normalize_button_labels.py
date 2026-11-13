"""Preserve safe formatted native-button labels as ordinary linked lesson text."""
import copy
from html import escape
from html.parser import HTMLParser
import re

from importer import Review
from normalize_editor_nodes import _core


CODE = 'button_label_html_preserved'
FIELDS = {'anchor','html','icon','linkType','url','blank','toAnchor','event'}
NULL_PRESENTATION_FIELDS = {'displayDelay','visibleConditions'}
INLINE = {'span','b','strong','i','em','u','s','sub','sup','mark','br'}


class _Label(HTMLParser):
    def __init__(self): super().__init__(convert_charrefs=True); self.ok=True; self.tags=0; self.text=[]
    def handle_starttag(self, tag, attrs):
        self.tags+=1
        if tag not in INLINE: self.ok=False
    def handle_startendtag(self, tag, attrs): self.handle_starttag(tag,attrs)
    def handle_data(self, data): self.text.append(data)
    def handle_comment(self, data): self.ok=False
    def handle_decl(self, decl): self.ok=False
    def handle_pi(self, data): self.ok=False
    def unknown_decl(self, data): self.ok=False


def _linked_label(node, validate):
    fields=node.get('fields',{}); label=fields.get('html'); url=fields.get('url')
    if (node.get('children') or set(fields)-FIELDS-NULL_PRESENTATION_FIELDS or fields.get('linkType')!='url'
            or any(fields.get(key) is not None for key in NULL_PRESENTATION_FIELDS)
            or any(fields.get(key) not in (None,'',False) for key in ('anchor','icon','toAnchor','event'))
            or not isinstance(label,str) or not label.strip() or ('<' not in label and '>' not in label)
            or not isinstance(url,str) or not _core()._url(url.strip())): return None
    # The shared converter already accepts line breaks in otherwise plain
    # labels. Retain their exact source structure and existing fingerprint.
    plain=re.sub(r'<br\s*/?>',' ',label,flags=re.I).strip()
    if '<' not in plain and '>' not in plain: return None
    blank=fields.get('blank')
    if not (blank is None or blank=='' or (type(blank) in (bool,int) and blank in (0,1))): return None
    if _core()._trainer_label(label) or _core()._possible_trainer_action(label): return None
    try:
        parsed=_Label(); parsed.feed(label); parsed.close()
        if not parsed.ok or not parsed.tags or not ''.join(parsed.text).strip(): return None
        window=' target="_blank" rel="noopener noreferrer"' if blank else ''
        markup='<p><a href="'+escape(url.strip(),quote=True)+'"'+window+'>'+label+'</a></p>'
        validate(markup)
    except (ValueError,UnicodeError,RecursionError): return None
    return markup


def normalize_button_labels(ape, validate_static):
    """Return copied APE plus metadata-only changes; leave unknown actions intact.

    The exact label HTML, trimmed URL, order, node identity and style are retained.
    The caller keeps the original APE alongside the normalized private snapshot.
    """
    if not callable(validate_static): raise Review('button_labels_validator_invalid')
    if not isinstance(ape,dict) or ape.get('name')!='page' or not isinstance(ape.get('children'),list):
        raise Review('button_labels_invalid')
    copied=copy.deepcopy(ape); changes=[]; visited=0
    def walk(node,path):
        nonlocal visited
        visited+=1
        if visited>150000 or len(path)>100 or not isinstance(node,dict) or not isinstance(node.get('name'),str):
            raise Review('button_labels_invalid')
        fields,children=node.get('fields',{}),node.get('children',[])
        if not isinstance(fields,dict) or not isinstance(children,list): raise Review('button_labels_invalid')
        if node['name']=='button':
            markup=_linked_label(node,validate_static)
            if markup is not None:
                node['name']='text'; node['fields']={'html':markup}
                changes.append({'path':list(path),'code':CODE})
        for index,child in enumerate(children): walk(child,path+[index])
    walk(copied,[])
    return copied,changes
