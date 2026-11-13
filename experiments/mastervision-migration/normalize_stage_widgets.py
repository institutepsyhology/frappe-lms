"""Preserve one verified authored stage-bar template without executing its JS."""
import copy
from decimal import Decimal
import hashlib
from html import escape
from html.parser import HTMLParser
import json
import re

from importer import Review
from normalize_editor_nodes import _style_content


CODE='static_course_stage_preserved'
# Verified across all 79 captured instances. No lesson HTML, script, label or
# percentage is embedded here; only caption and numeric data-progress may vary.
DOM_SHA256='9821b438bcd27b95361ead018c31fb6999324268cec308e3ea092ea4aca27e65'
SCRIPT_SHA256='98b73eb48a802d3127c28e8e32d4522125f0d2537e0a79ba027da8e5b17830c3'
STYLESHEET_SHA256='80c3cc926ce38583d602cdeb45ffde7f789b0adb3ac4e04181ab3fc7c2fb82d9'
NODE_KEYS={'id','name','fields','children','style'}


def _sha(value):return hashlib.sha256(value.encode('utf-8')).hexdigest()


class _DOM(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.root=[];self.stack=[];self.count=0
    def handle_starttag(self,tag,attrs):
        self.count+=1
        if (tag not in {'div','style','script'} or self.count>12 or len(self.stack)>8
                or len(dict(attrs))!=len(attrs)):raise ValueError('unknown_stage_structure')
        node={'tag':tag,'attrs':dict(attrs),'children':[]}
        (self.stack[-1]['children'] if self.stack else self.root).append(node);self.stack.append(node)
    def handle_startendtag(self,tag,attrs):raise ValueError('unknown_stage_structure')
    def handle_endtag(self,tag):
        if not self.stack or self.stack[-1]['tag']!=tag:raise ValueError('unknown_stage_structure')
        self.stack.pop()
    def handle_data(self,value):(self.stack[-1]['children'] if self.stack else self.root).append(value)
    def handle_comment(self,value):raise ValueError('unknown_stage_structure')
    def handle_decl(self,value):raise ValueError('unknown_stage_structure')
    def handle_pi(self,value):raise ValueError('unknown_stage_structure')
    def unknown_decl(self,value):raise ValueError('unknown_stage_structure')


def _template(markup):
    if not isinstance(markup,str):return None
    try:
        if len(markup.encode('utf-8'))>200000:return None
        parser=_DOM();parser.feed(markup);parser.close()
        if parser.stack:return None
        labels=[];numbers=[];templates=[]
        def mask(value):
            if isinstance(value,str):return None if not value.strip() else value
            tag=value['tag'];attrs=dict(value['attrs']);children=value['children']
            if 'data-progress' in attrs:
                number=attrs['data-progress']
                if (not isinstance(number,str) or not re.fullmatch(r'[0-9]{1,3}(?:\.[0-9]{1,8})?',number)
                        or not 0<=Decimal(number)<=100):raise ValueError('unknown_stage_number')
                numbers.append(number);attrs['data-progress']='@progress'
            if tag in ('script','style'):
                if not all(isinstance(child,str) for child in children):raise ValueError('unknown_stage_structure')
                digest=_sha(''.join(children))
                if digest!=(SCRIPT_SHA256 if tag=='script' else STYLESHEET_SHA256):raise ValueError('unknown_stage_template')
                templates.append(tag);children=[{'sha256':digest}]
            elif tag=='div' and any(isinstance(child,str) and child.strip() for child in children):
                if not all(isinstance(child,str) for child in children):raise ValueError('unknown_stage_caption')
                label=''.join(children)
                if len(label)>512 or not label.strip():raise ValueError('unknown_stage_caption')
                labels.append(label);children=['@label']
            else:children=[masked for child in children if (masked:=mask(child)) is not None]
            return {'tag':tag,'attrs':attrs,'children':children}
        masked=[value for child in parser.root if (value:=mask(child)) is not None]
        canonical=json.dumps(masked,ensure_ascii=True,sort_keys=True,separators=(',',':'))
        if (_sha(canonical)!=DOM_SHA256 or len(labels)!=1 or len(numbers)!=1
                or templates!=['style','script']):return None
        return labels[0],numbers[0]
    except (ValueError,UnicodeError,RecursionError):return None


def normalize_stage_widgets(ape,validate_static):
    """Return a copied tree plus metadata-only replacements of the known widget.

    Percentages describe the authored course stage, never a learner's progress.
    Unknown scripts, markup, actions and visibility conditions remain unchanged.
    The caller retains the exact original APE alongside normalization metadata.
    """
    if not callable(validate_static):raise Review('stage_widgets_validator_invalid')
    if not isinstance(ape,dict) or ape.get('name')!='page' or not isinstance(ape.get('children'),list):
        raise Review('stage_widgets_invalid')
    try:copied=copy.deepcopy(ape)
    except (TypeError,RecursionError):raise Review('stage_widgets_invalid') from None
    visited=0;changes=[]
    def walk(node,path):
        nonlocal visited
        visited+=1
        if visited>150000 or len(path)>100 or not isinstance(node,dict) or not isinstance(node.get('name'),str):
            raise Review('stage_widgets_invalid')
        fields,children=node.get('fields',{}),node.get('children',[])
        if not isinstance(fields,dict) or not isinstance(children,list):raise Review('stage_widgets_invalid')
        if fields.get('visibleConditions') not in (None,'',False,[],{}):return
        if node['name']=='code':
            if (children or set(node)-NODE_KEYS or set(fields)-{'anchor','html'}
                    or fields.get('anchor') not in (None,'') or _style_content(node.get('style'))):return
            result=_template(fields.get('html'))
            if result is None:return
            label,number=result
            markup='<p><strong>'+escape(label)+'</strong> · '+number+'%</p>'
            try:validate_static(markup)
            except (ValueError,UnicodeError,RecursionError):return
            node['name']='text';node['fields']={'html':markup}
            changes.append({'path':list(path),'code':CODE})
        else:
            for index,child in enumerate(children):walk(child,path+[index])
    walk(copied,[])
    return copied,changes
