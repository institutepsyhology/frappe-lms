"""Build an inert local Frappe HTML-block candidate without modifying source HTML.

This deliberately admits only simple static markup. Unrecognized markup must be
reviewed; it must never silently be executed or dropped during migration.
"""
import base64
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

TAGS={'p','div','span','h1','h2','h3','h4','h5','h6','strong','b','em','i','u','s','a','hr','br','ul','ol','li','blockquote'}
VOID={'br','hr'}
ATTRS={'class','style','href','target','title'}
CSS={'box-sizing','margin-top','border','color','font-family','font-size','border-bottom','padding'}
CLASSES={'lesson-mission-wrapper','lesson-mission-text'}
CLASS=re.compile(r'^[A-Za-z0-9_ -]{1,160}$')
CSS_VALUE=re.compile(r'^[\w\s#.,%()\'"+\-]{1,300}$',re.UNICODE)


def valid_link(value):
    if not isinstance(value,str) or not value or len(value)>4096 or re.search(r'[\x00-\x20\x7f\\]',value):return False
    try:
        u=urlsplit(value)
        return u.scheme in ('http','https') and bool(u.hostname) and not u.username and not u.password and u.port in (None,80,443)
    except ValueError:return False


def valid_style(value):
    if not isinstance(value,str) or len(value)>2000:return False
    parts=[x.strip() for x in value.split(';') if x.strip()]
    if not parts:return False
    for item in parts:
        if ':' not in item:return False
        key,val=(x.strip() for x in item.split(':',1))
        if key.lower() not in CSS or not CSS_VALUE.fullmatch(val):return False
        if re.search(r'(?:url|expression)\s*\(',val,re.I):return False
    return True


class StaticHTML(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.stack=[];self.links=0
    def handle_starttag(self,tag,attrs):
        if tag not in TAGS or len({k for k,v in attrs})!=len(attrs):raise ValueError('unsupported_html')
        for key,value in attrs:
            if key not in ATTRS:raise ValueError('unsupported_attribute')
            if key=='href' and (tag!='a' or not valid_link(value)):raise ValueError('invalid_link')
            if key=='target' and (tag!='a' or value not in ('_blank','_self')):raise ValueError('invalid_target')
            if key=='class' and (not isinstance(value,str) or not CLASS.fullmatch(value) or not set(value.split()).issubset(CLASSES)):raise ValueError('invalid_class')
            if key=='style' and not valid_style(value):raise ValueError('invalid_style')
        if tag=='a':
            if sum(k=='href' for k,v in attrs)!=1:raise ValueError('missing_link')
            self.links+=1
        if tag not in VOID:self.stack.append(tag)
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in VOID:self.handle_endtag(tag)
    def handle_endtag(self,tag):
        if tag in VOID:return
        if not self.stack or self.stack.pop()!=tag:raise ValueError('unbalanced_html')
    def handle_comment(self,data):raise ValueError('unsupported_html')
    def handle_decl(self,decl):raise ValueError('unsupported_html')
    def handle_pi(self,data):raise ValueError('unsupported_html')
    def unknown_decl(self,data):raise ValueError('unsupported_html')


def make_html_block(source):
    if not isinstance(source,str) or not source:raise ValueError('invalid_html')
    raw=source.encode('utf-8',errors='strict')
    if len(raw)>200000:raise ValueError('html_too_large')
    parser=StaticHTML();parser.feed(source);parser.close()
    if parser.stack:raise ValueError('unbalanced_html')
    return {'type':'htmlBlock','data':{'encodedHtml':base64.b64encode(raw).decode('ascii'),'height':1600}}
