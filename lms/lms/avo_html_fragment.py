"""Build an inert local Frappe HTML-block candidate without modifying source HTML.

This deliberately admits only simple static markup. Unrecognized markup must be
reviewed; it must never silently be executed or dropped during migration.
"""
import base64
from html import escape, unescape
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

TAGS={'p','div','span','h1','h2','h3','h4','h5','h6','strong','b','em','i','u','s','a','hr','br','ul','ol','li','blockquote','font','style','iframe'}
VOID={'br','hr'}
ATTRS={'class','style','href','target','title','savefrom_lm','savefrom_lm_index','dir','span','id','data-xdget-id','data-block-id','data-updated','data-code','data-editable','data-main-class','data-param','color','type','src','width','height'}
CSS={'box-sizing','margin-top','border','color','font-family','font-size','border-bottom','padding',
     'background-color','font-weight','text-decoration-line','margin','line-height','vertical-align',
     'white-space','z-index','background','margin-right','margin-left','margin-bottom','background-image',
     'background-position','background-size','background-repeat','background-attachment','background-origin',
     'background-clip','position','min-height','padding-right','padding-left','width','overflow','padding-bottom','padding-top','max-width','flex','text-align','float'}
CLASSES={'lesson-mission-wrapper','lesson-mission-text','redactor-inline-converted','xdget-block',
         'xdget-div','center-block','row-section','xdget-common-container','div','xdget-visible-to-bg-',
         'xdget-lessonContent','row','content-row','col-md-12','xdget-lessonFiles','xdget-lessonMission',
         'xdget-lessonAnswers','self-answers','lesson-send-answer-block','lite-block-live-wrapper','o-lt-lesson',
         'o-lt-lesson-mission-block','lmb1','lt-block','lt-lesson','lt-lesson-mission-block','lt-view','lt-block-wrapper','container',
         'o-lt-lesson-files','lessonFiles01','lt-lesson-files','block-box','modal-block-content','text-left','files-row',
         'o-lt-separator','lt-separator','separator01','o-lt-lesson-header','lessonHdr01','lt-lesson-header','header','f-header','f-lesson-header-1'}
CLASS=re.compile(r'^[A-Za-z0-9_ -]{1,160}$')
CSS_VALUE=re.compile(r'^[\w\s#.,%()\'"+\-]{1,300}$',re.UNICODE)
SAFE_CLIPBOARD_CSS='<!--td {border: 1px solid #ccc;}br {mso-data-placement:same-cell;}-->'


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
        if key.lower()=='position' and val.lower() not in ('static','relative'):return False
        if key.lower()=='background-image' and val.lower() not in ('none','initial'):return False
        if key.lower()=='z-index' and (not val.isdigit() or int(val)>1000):return False
        if key.lower()=='overflow' and val.lower() not in ('hidden','auto','visible','scroll'):return False
        if key.lower()=='text-align' and val.lower() not in ('left','right','center','justify','start','end'):return False
        if key.lower()=='flex' and val!='1 1 100%':return False
        if key.lower()=='float' and val.lower() not in ('left','right','none'):return False
    return True


class StaticHTML(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.stack=[];self.links=0;self.answers_depth=None;self.stylesheet=None
    def handle_starttag(self,tag,attrs):
        if tag not in TAGS or len({k for k,v in attrs})!=len(attrs):raise ValueError('unsupported_html')
        if tag=='iframe':
            a=dict(attrs)
            if (set(a)!={'src','width','height'} or a['width']!='640' or a['height']!='480'
                    or not re.fullmatch(r'https://drive\.google\.com/file/d/[A-Za-z0-9_-]{1,200}/preview',a['src'])):
                raise ValueError('unsupported_iframe')
        if self.stylesheet is not None:raise ValueError('unsupported_html')
        if self.answers_depth is not None and (tag not in ('div','p','span','br') or any(k not in ('class','style') for k,v in attrs)):
            raise ValueError('answers_not_empty')
        for key,value in attrs:
            if key not in ATTRS:raise ValueError('unsupported_attribute')
            if key in ('src','width','height') and tag!='iframe':raise ValueError('unsupported_attribute')
            if key=='href' and (tag!='a' or not valid_link(value)):raise ValueError('invalid_link')
            if key=='target' and (tag!='a' or value not in ('_blank','_self')):raise ValueError('invalid_target')
            if key=='savefrom_lm' and (tag!='a' or value!='1'):raise ValueError('unsupported_attribute')
            if key=='savefrom_lm_index' and (tag!='a' or not isinstance(value,str) or not re.fullmatch(r'[0-9]{1,6}',value)):raise ValueError('unsupported_attribute')
            if key=='dir' and value not in ('ltr','rtl','auto'):raise ValueError('unsupported_attribute')
            if key=='span' and (tag!='a' or value not in ('',None)):raise ValueError('unsupported_attribute')
            if key=='data-xdget-id' and (tag!='div' or not isinstance(value,str) or not re.fullmatch(r'[0-9]{1,12}',value)):raise ValueError('unsupported_attribute')
            if key in ('data-block-id','data-updated') and (tag!='div' or not isinstance(value,str) or not re.fullmatch(r'[0-9]{1,12}',value)):raise ValueError('unsupported_attribute')
            if key=='data-code' and (tag!='div' or not isinstance(value,str) or not re.fullmatch(r'(?:ltBlock[0-9]{1,12}|b-[0-9a-f]{5})',value)):raise ValueError('unsupported_attribute')
            if key in ('data-editable','data-main-class','data-param') and (tag!='div' or value!=('true' if key=='data-editable' else 'header')):raise ValueError('unsupported_attribute')
            if key=='id' and (not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',value)):raise ValueError('unsupported_attribute')
            if key=='color' and (tag!='font' or not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value)):raise ValueError('unsupported_attribute')
            if key=='type' and (tag!='style' or value!='text/css'):raise ValueError('unsupported_attribute')
            if key=='class' and (not isinstance(value,str) or not CLASS.fullmatch(value) or not set(value.split()).issubset(CLASSES)):raise ValueError('invalid_class')
            if key=='style' and not valid_style(value):raise ValueError('invalid_style')
        if tag=='a':
            if sum(k=='href' for k,v in attrs)!=1:raise ValueError('missing_link')
            self.links+=1
        if tag=='style':
            if dict(attrs)!={'type':'text/css'}:raise ValueError('unsupported_attribute')
            self.stylesheet=''
        if {'xdget-lessonAnswers','self-answers'} & set(dict(attrs).get('class','').split()):
            if tag!='div' or self.answers_depth is not None:raise ValueError('answers_not_empty')
            self.answers_depth=len(self.stack)+1
        if tag not in VOID:self.stack.append(tag)
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in VOID:self.handle_endtag(tag)
    def handle_endtag(self,tag):
        if tag in VOID:return
        if tag=='style':
            if self.stylesheet != SAFE_CLIPBOARD_CSS:raise ValueError('unsupported_stylesheet')
            self.stylesheet=None
        if not self.stack or self.stack.pop()!=tag:raise ValueError('unbalanced_html')
        if self.answers_depth is not None and len(self.stack)<self.answers_depth:self.answers_depth=None
    def handle_data(self,data):
        if self.answers_depth is not None and data.strip():raise ValueError('answers_not_empty')
        if self.stylesheet is not None:
            self.stylesheet+=data
            if len(self.stylesheet)>len(SAFE_CLIPBOARD_CSS):raise ValueError('unsupported_stylesheet')
    def handle_comment(self,data):raise ValueError('unsupported_html')
    def handle_decl(self,decl):raise ValueError('unsupported_html')
    def handle_pi(self,data):raise ValueError('unsupported_html')
    def unknown_decl(self,data):raise ValueError('unsupported_html')


def strip_empty_answer_form(source):
    """Remove exactly one empty known answer form, preserving all other bytes."""
    if not isinstance(source,str) or not source:raise ValueError('invalid_html')
    starts=[0]+[i+1 for i,c in enumerate(source) if c=='\n']
    class Form(HTMLParser):
        def __init__(self):super().__init__(convert_charrefs=True);self.stack=[];self.start=None;self.end=None;self.classes=set()
        def source_index(self):
            line,column=self.getpos()
            return starts[line-1]+column
        def handle_starttag(self,tag,attrs):
            if tag=='form':
                if self.start is not None or self.stack:raise ValueError('unsupported_form')
                a=dict(attrs)
                if (len(a)!=len(attrs) or set(a)-{'action','enctype','id','method','style','class'}
                        or a.get('method','').lower()!='post' or a.get('enctype')!='multipart/form-data'
                        or not a.get('action')):raise ValueError('unsupported_form')
                self.start=self.source_index();self.stack.append(tag);return
            if self.stack:
                if tag!='div' or len(dict(attrs))!=len(attrs) or set(dict(attrs))-{'class','style'}:raise ValueError('unsupported_form')
                values=set((dict(attrs).get('class') or '').split())
                if not values.issubset({'answer-form','answer-form-content','answer-textarea-container'}):raise ValueError('unsupported_form')
                self.classes.update(values);self.stack.append(tag)
        def handle_startendtag(self,tag,attrs):
            if self.stack:raise ValueError('unsupported_form')
        def handle_endtag(self,tag):
            if not self.stack:return
            if self.stack.pop()!=tag:raise ValueError('unsupported_form')
            if not self.stack:
                end=source.find('>',self.source_index())
                if tag!='form' or end<0:raise ValueError('unsupported_form')
                self.end=end+1
        def handle_data(self,data):
            if self.stack and data.strip():raise ValueError('unsupported_form')
        def handle_comment(self,data):
            if self.stack:raise ValueError('unsupported_form')
        def handle_decl(self,data):
            if self.stack:raise ValueError('unsupported_form')
        def handle_pi(self,data):
            if self.stack:raise ValueError('unsupported_form')
    parser=Form();parser.feed(source);parser.close()
    if (parser.stack or parser.start is None or parser.end is None or
            parser.classes!={'answer-form','answer-form-content','answer-textarea-container'}):
        raise ValueError('unsupported_form')
    return source[:parser.start]+source[parser.end:]


def replace_drive_audio(source):
    """Replace reviewed legacy Google audio embeds with their file-view links."""
    if not isinstance(source,str):raise ValueError('invalid_html')
    pattern=(r'<audio controls="" controlslist="nodownload"(?: title="hello world")?><source src="'
             r'https://drive\.google\.com/uc\?export=view&amp;id=([A-Za-z0-9_-]{1,200})"\s*/></audio>')
    result,count=re.subn(pattern,lambda m:'<a href="https://drive.google.com/file/d/'+m.group(1)+'/view" target="_blank">АУДИОЗАПИСЬ</a>',source)
    if count<1 or re.search(r'<\s*/?\s*(?:audio|source)\b',result,re.I):raise ValueError('unsupported_audio')
    return result


def split_reviewed_audio_links(source):
    """Keep links outside the sandboxed HTML frame and preserve block order."""
    converted=replace_drive_audio(source)
    pattern=r'<p(?:\s[^>]*)?>\s*<a\s([^>]*)>([^<]*)</a>\s*</p>'
    blocks=[]; position=0; links=0
    for match in re.finditer(pattern,converted,re.I):
        before=converted[position:match.start()]
        if before.strip():blocks.append(make_html_block(before))
        class Anchor(HTMLParser):
            def handle_starttag(self,tag,attrs):self.attrs=attrs
        parser=Anchor();parser.feed('<a '+match.group(1)+'>')
        attrs=dict(parser.attrs)
        if len(attrs)!=len(parser.attrs) or not valid_link(attrs.get('href')):raise ValueError('invalid_link')
        text=unescape(match.group(2)).strip()
        if not text:raise ValueError('invalid_link')
        blocks.append({'type':'paragraph','data':{'text':'<a href="'+escape(attrs['href'],quote=True)+'">'+escape(text)+'</a>'}})
        links+=1;position=match.end()
    if links<1:raise ValueError('missing_audio_link')
    after=converted[position:]
    if after.strip():blocks.append(make_html_block(after))
    return blocks


def make_html_block(source):
    if not isinstance(source,str) or not source:raise ValueError('invalid_html')
    raw=source.encode('utf-8',errors='strict')
    if len(raw)>200000:raise ValueError('html_too_large')
    parser=StaticHTML();parser.feed(source);parser.close()
    if parser.stack:raise ValueError('unbalanced_html')
    return {'type':'htmlBlock','data':{'encodedHtml':base64.b64encode(raw).decode('ascii'),'height':1600}}
