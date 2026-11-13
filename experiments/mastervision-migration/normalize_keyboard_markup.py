"""Preserve keyboard text while removing only observed inert presentation CSS."""
import copy
from html import escape
from html.parser import HTMLParser
import re

from importer import Review
from normalize_static_presentation import _content_style, _material, _visual_value, VISUAL_TEXT_STYLE, VOID
from normalize_editor_nodes import _style_content

CODE = 'keyboard_markup_normalized'
REMOVABLE = {'border-radius':'4px',
             'box-shadow':'rgba(0, 0, 0, 0.25) 0px -1px 0px inset',
             'display':'inline-block'}
FORBIDDEN = {'script','style','form','input','select','textarea','object','embed',
             'svg','math','audio','video','meta','link','base'}


def _review(): raise Review('keyboard_markup_requires_review')


def _protected_style(style):
    # AVO names this exact visual alignment wrapper "content"; it contains no
    # lesson material. Only the guard probe changes, never original metadata.
    if isinstance(style,dict) and isinstance(style.get('lists'),dict):
        probe = copy.deepcopy(style)
        content = style['lists'].get('content')
        if content == {'justifyContent':{'value':{'type':'center'}}}:
            probe['lists'].pop('content')
        elif content not in (None,'',False,[],{}): return True
        visual = style['lists'].get('text')
        if (isinstance(visual,dict) and not set(visual) - (VISUAL_TEXT_STYLE | {'color','fontSize'})
                and all(_visual_value(value) for value in visual.values())
                and not _style_content(visual)):
            probe['lists'].pop('text')
        return _content_style(probe)
    return _content_style(style)


class _Keyboard(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.output, self.stack = [], []
        self.count = self.elements = self.removed = 0

    def _attributes(self, attrs):
        if set(dict(attrs)) - {'style'}: _review()
        style = dict(attrs).get('style','')
        if not isinstance(style,str): _review()
        parts, seen = [], set()
        for piece in style.split(';'):
            if not piece.strip(): continue
            if ':' not in piece: _review()
            name, value = (part.strip() for part in piece.split(':',1))
            lowered = name.lower()
            if lowered in seen: _review()
            seen.add(lowered)
            if lowered in REMOVABLE:
                if value != REMOVABLE[lowered]: _review()
                self.removed += 1
            else: parts.append(piece)
        if 'font-family' not in seen: parts.append('font-family:monospace')
        return [('style',';'.join(parts))]

    def handle_starttag(self, tag, attrs):
        self.count += 1
        if (self.count > 50000 or len(self.stack) > 100 or len(dict(attrs)) != len(attrs)
                or tag in FORBIDDEN or any(key.startswith('on') for key,_ in attrs)):
            _review()
        mapped = tag
        if tag == 'kbd':
            attrs = self._attributes(attrs); mapped = 'span'; self.elements += 1
        attributes = ''.join(' ' + key + ('' if value is None else '="' + escape(value,quote=True) + '"')
                             for key,value in attrs)
        self.output.append('<' + mapped + attributes + '>')
        if tag not in VOID: self.stack.append((tag,mapped))

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1][0] != tag: _review()
        _,mapped = self.stack.pop(); self.output.append('</' + mapped + '>')

    def handle_startendtag(self, tag, attrs):
        if tag not in VOID: _review()
        self.handle_starttag(tag,attrs)

    def handle_data(self, value): self.output.append(escape(value,quote=False))
    def handle_entityref(self, name): self.output.append('&' + name + ';')
    def handle_charref(self, name): self.output.append('&#' + name + ';')
    def handle_comment(self, _): _review()
    def handle_decl(self, _): _review()
    def handle_pi(self, _): _review()
    unknown_decl = handle_decl

    def finish(self):
        self.close()
        if self.stack: _review()
        return ''.join(self.output)


def _clean(source, validate):
    if not re.search(r'<\s*kbd\b',source,re.I): return None
    try: validate(source)
    except (TypeError,ValueError,UnicodeError,RecursionError): pass
    else: return None  # Never alter HTML already accepted by the converter.
    try:
        if len(source.encode('utf-8')) > 200000: _review()
    except UnicodeError: _review()
    parser = _Keyboard(); parser.feed(source); cleaned = parser.finish()
    if not parser.elements: return None
    try: validate(cleaned)
    except (TypeError,ValueError,UnicodeError,RecursionError): _review()
    if _material(source) != _material(cleaned):
        raise Review('keyboard_markup_material_mismatch')
    return cleaned, parser.elements, parser.removed


def normalize_keyboard_markup(ape, validate_static):
    """Return copied APE and fixed metadata; the caller retains original source."""
    if (not callable(validate_static) or not isinstance(ape,dict) or ape.get('name') != 'page'
            or not isinstance(ape.get('children'),list)):
        raise Review('keyboard_markup_source_invalid')
    copied,changes,visited = copy.deepcopy(ape),[],0
    def walk(node,path,protected=False):
        nonlocal visited
        visited += 1
        if (visited > 150000 or len(path) > 100 or not isinstance(node,dict)
                or not isinstance(node.get('name'),str) or not isinstance(node.get('fields',{}),dict)
                or not isinstance(node.get('children',[]),list)):
            raise Review('keyboard_markup_source_invalid')
        fields = node.get('fields',{})
        protected = (protected or fields.get('anchor') not in (None,'')
                     or any(fields.get(key) not in (None,'',False,[],{})
                            for key in ('visibleConditions','displayDelay'))
                     or _protected_style(node.get('style')))
        if (not protected and node['name'] == 'text' and not node.get('children')
                and not set(fields) - {'html','anchor','visibleConditions','displayDelay'}
                and not set(node) - {'id','name','fields','children','style'}
                and isinstance(fields.get('html'),str)):
            result = _clean(fields['html'],validate_static)
            if result:
                fields['html'],elements,removed = result
                changes.append({'path':list(path),'code':CODE,
                                'keyboard_elements':elements,'presentation_removed':removed})
        for index,child in enumerate(node.get('children',[])): walk(child,path+(index,),protected)
    walk(copied,())
    return copied,changes
