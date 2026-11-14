"""Build an inert local Frappe HTML-block candidate without modifying source HTML.

This deliberately admits only simple static markup. Unrecognized markup must be
reviewed; it must never silently be executed or dropped during migration.
"""
import base64
from html import escape, unescape
from html.parser import HTMLParser
import re
from urllib.parse import parse_qsl, urlsplit

TAGS={'p','div','span','h1','h2','h3','h4','h5','h6','strong','b','em','i','u','s','a','hr','br','ul','ol','li','blockquote','font','style','iframe','sub','sup','mark','table','colgroup','col','tbody','tr','td'}
VOID={'br','hr','col'}
ATTRS={'class','style','href','target','rel','title','savefrom_lm','savefrom_lm_index','dir','span','id','data-xdget-id','data-block-id','data-updated','data-code','data-editable','data-main-class','data-param','color','face','type','src','width','height','aria-level','start','role','colspan','rowspan','allow','frameborder','allowfullscreen'}
CSS={'box-sizing','margin-top','border','color','font-family','font-size','border-bottom','padding',
     'background-color','font-weight','text-decoration-line','margin','line-height','vertical-align',
     'white-space','z-index','background','margin-right','margin-left','margin-bottom','background-image',
     'background-position','background-size','background-repeat','background-attachment','background-origin',
     'background-clip','position','min-height','padding-right','padding-left','width','overflow','padding-bottom','padding-top','max-width','flex','text-align','float','outline',
     'font-variant','font-style','text-decoration','border-collapse','border-top','border-right','border-left','overflow-wrap',
     'font-variant-numeric','font-variant-east-asian','list-style-type','height','border-top-color',
     'text-decoration-skip-ink','-webkit-text-decoration-skip','text-indent',
     'font-variant-ligatures','text-decoration-style','text-decoration-color','border-width','border-right-style',
     'border-bottom-style','border-left-style','border-right-color','border-bottom-color','border-left-color',
     'border-image','border-top-style','list-style','margin-inline-start','margin-inline-end'}
CLASSES={'lesson-mission-wrapper','lesson-mission-text','redactor-inline-converted','xdget-block',
         'xdget-div','center-block','row-section','xdget-common-container','div','xdget-visible-to-bg-',
         'xdget-lessonContent','row','content-row','col-md-12','xdget-lessonFiles','xdget-lessonMission',
         'xdget-lessonAnswers','self-answers','lesson-send-answer-block','lite-block-live-wrapper','o-lt-lesson',
         'o-lt-lesson-mission-block','lmb1','lt-block','lt-lesson','lt-lesson-mission-block','lt-view','lt-block-wrapper','container',
         'o-lt-lesson-files','lessonFiles01','lt-lesson-files','block-box','modal-block-content','text-left','files-row',
         'o-lt-separator','lt-separator','separator01','o-lt-lesson-header','lessonHdr01','lt-lesson-header','header','f-header','f-lesson-header-1',
         'o-lt-video','o-lt-video-hosting-with-defence','vid03','lt-video','lt-video-hosting-with-defence',
         'gc-main-content','gc-both-main-content','wide','account-page-content','with-left-menu','gc-user-logined','gc-user-admin',
         'page-full-block','main-page-block','full-width','xdget-root','xdget-lesson','main-lesson-container',
         'o-lt-lesson-text','lessonTxt01','lt-lesson-text','text','f-text','o-lt-lesson-video','lessonVid01','lt-lesson-video'}
CLASS=re.compile(r'^[A-Za-z0-9_ -]{1,160}$')
CSS_VALUE=re.compile(r'^[\w\s#.,%()\'"+\-]{1,300}$',re.UNICODE)
SAFE_CLIPBOARD_CSS='<!--td {border: 1px solid #ccc;}br {mso-data-placement:same-cell;}-->'


def valid_link(value):
    if not isinstance(value,str) or not value or len(value)>4096 or re.search(r'[\x00-\x20\x7f\\]',value):return False
    # A single plain mailbox has no executable URL, headers or body payload.
    if value.startswith('mailto:'):
        return len(value)<=320 and bool(re.fullmatch(r'mailto:[A-Za-z0-9.!$\x27*+/=_`{|}~-]{1,64}@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}',value))
    try:
        u=urlsplit(value)
        return u.scheme in ('http','https') and bool(u.hostname) and not u.username and not u.password and u.port in (None,80,443)
    except ValueError:return False


def valid_vk_frame(attrs):
    """Allow only the observed public VK embed shape, never general iframes."""
    if set(attrs)!={'src','width','height','allow','frameborder','allowfullscreen'}:
        return False
    if attrs['frameborder']!='0' or attrs['allowfullscreen'] not in (None,'','true','allowfullscreen'):
        return False
    for key in ('width','height'):
        value=attrs[key]
        if not isinstance(value,str) or not re.fullmatch(r'[1-9][0-9]{0,3}',value) or int(value)>4096:
            return False
    features=attrs['allow']
    if (not isinstance(features,str) or len(features)>160
            or {v.strip() for v in features.split(';') if v.strip()} !=
            {'autoplay','encrypted-media','fullscreen','picture-in-picture','screen-wake-lock'}):
        return False
    source=attrs['src']
    if not isinstance(source,str) or len(source)>1000 or re.search(r'[\x00-\x20\x7f\\]',source):
        return False
    try:
        url=urlsplit(source)
        if (url.scheme!='https' or url.hostname not in ('vk.com','vkvideo.ru')
                or url.username is not None or url.password is not None or url.port is not None
                or url.fragment or url.path!='/video_ext.php'):
            return False
        pairs=parse_qsl(url.query,keep_blank_values=True,strict_parsing=True)
        query=dict(pairs)
        if len(query)!=len(pairs) or set(query) not in ({'oid','id','hash','hd'},{'oid','id','hash','hd','autoplay'}):
            return False
        return (bool(re.fullmatch(r'-?[1-9][0-9]{0,11}',query['oid']))
                and bool(re.fullmatch(r'[1-9][0-9]{0,11}',query['id']))
                and bool(re.fullmatch(r'[0-9a-f]{16}',query['hash']))
                and query['hd'] in ('2','4') and query.get('autoplay','0') in ('0','1'))
    except (ValueError,UnicodeError):
        return False


def valid_style(value):
    if not isinstance(value,str) or len(value)>2000:return False
    parts=[x.strip() for x in value.split(';') if x.strip()]
    if not parts:return False
    for item in parts:
        if ':' not in item:return False
        key,val=(x.strip() for x in item.split(':',1))
        if key.lower() not in CSS or not CSS_VALUE.fullmatch(val):return False
        if re.search(r'(?:url|expression)\s*\(',val,re.I):return False
        if key.lower()=='list-style' and val.lower() not in ('none','decimal','disc','circle','square'):return False
        if key.lower() in ('margin-inline-start','margin-inline-end') and not re.fullmatch(r'(?:-?\d+(?:\.\d+)?(?:px|em|rem|%)|0|auto)',val,re.I):return False
        if key.lower()=='position' and val.lower() not in ('static','relative'):return False
        if key.lower()=='background-image' and val.lower() not in ('none','initial'):return False
        if key.lower()=='z-index' and (not val.isdigit() or int(val)>1000):return False
        if key.lower()=='overflow' and val.lower() not in ('hidden','auto','visible','scroll'):return False
        if key.lower()=='text-align' and val.lower() not in ('left','right','center','justify','start','end'):return False
        if key.lower()=='flex' and val!='1 1 100%':return False
        if key.lower()=='float' and val.lower() not in ('left','right','none'):return False
        if key.lower()=='outline' and val not in ('0','0px','none'):return False
        if key.lower() in ('font-variant-numeric','font-variant-east-asian') and val.lower()!='normal':return False
        if key.lower()=='font-variant-ligatures' and val.lower()!='normal':return False
        if key.lower() in ('text-decoration-style','text-decoration-color') and val.lower()!='initial':return False
        if key.lower()=='border-width' and not re.fullmatch(r'[0-9]{1,2}px(?:\s+[0-9]{1,2}px){0,3}',val):return False
        if key.lower() in ('border-right-style','border-bottom-style','border-left-style','border-right-color','border-bottom-color','border-left-color','border-image') and val.lower()!='initial':return False
        if key.lower()=='border-top-style' and val.lower()!='solid':return False
        if key.lower()=='list-style-type' and val.lower() not in ('decimal','lower-alpha','disc'):return False
        if key.lower() in ('text-decoration-skip-ink','-webkit-text-decoration-skip') and val.lower()!='none':return False
        if key.lower()=='height' and val!='0px':return False
    return True


class StaticHTML(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.stack=[];self.links=0;self.answers_depth=None;self.stylesheet=None
    def handle_starttag(self,tag,attrs):
        if tag not in TAGS or len({k for k,v in attrs})!=len(attrs):raise ValueError('unsupported_html')
        if tag=='iframe':
            a=dict(attrs)
            drive=(set(a)=={'src','width','height'} and a['width']=='640' and a['height']=='480'
                   and isinstance(a['src'],str) and bool(re.fullmatch(r'https://drive\.google\.com/file/d/[A-Za-z0-9_-]{1,200}/preview',a['src'])))
            if not drive and not valid_vk_frame(a):
                raise ValueError('unsupported_iframe')
        if self.stylesheet is not None:raise ValueError('unsupported_html')
        if self.answers_depth is not None and (tag not in ('div','p','span','br') or any(k not in ('class','style') for k,v in attrs)):
            raise ValueError('answers_not_empty')
        for key,value in attrs:
            if key not in ATTRS:raise ValueError('unsupported_attribute')
            if key=='role' and (tag!='p' or value!='presentation'):raise ValueError('unsupported_attribute')
            if key in ('src','height') and tag!='iframe':raise ValueError('unsupported_attribute')
            if key in ('allow','frameborder','allowfullscreen') and tag!='iframe':raise ValueError('unsupported_attribute')
            if key in ('colspan','rowspan') and (tag!='td' or not isinstance(value,str)
                    or not re.fullmatch(r'[1-9]|1[0-6]',value)):
                raise ValueError('unsupported_attribute')
            if key=='width' and tag!='iframe':
                if tag not in ('table','col') or not isinstance(value,str) or not re.fullmatch(r'[1-9][0-9]{0,3}',value):raise ValueError('unsupported_attribute')
            if key in ('aria-level','start'):
                if ((key=='aria-level' and tag!='li') or (key=='start' and tag!='ol')
                        or not isinstance(value,str) or not re.fullmatch(r'[1-9][0-9]{0,2}',value)):
                    raise ValueError('unsupported_attribute')
            if key=='href' and (tag!='a' or not valid_link(value)):raise ValueError('invalid_link')
            if key=='target' and (tag!='a' or value not in ('_blank','_self')):raise ValueError('invalid_target')
            if key=='rel' and (tag!='a' or not isinstance(value,str) or not set(value.split()).issubset({'noopener','noreferrer','nofollow'})):raise ValueError('invalid_link')
            if key=='savefrom_lm' and (tag!='a' or value!='1'):raise ValueError('unsupported_attribute')
            if key=='savefrom_lm_index' and (tag!='a' or not isinstance(value,str) or not re.fullmatch(r'[0-9]{1,6}',value)):raise ValueError('unsupported_attribute')
            if key=='dir' and value not in ('ltr','rtl','auto'):raise ValueError('unsupported_attribute')
            if key=='span' and (tag!='a' or value not in ('',None)):raise ValueError('unsupported_attribute')
            if key=='data-xdget-id' and (tag!='div' or not isinstance(value,str) or not re.fullmatch(r'[0-9]{1,12}',value)):raise ValueError('unsupported_attribute')
            if key in ('data-block-id','data-updated') and (tag!='div' or not isinstance(value,str) or not re.fullmatch(r'[0-9]{1,12}',value)):raise ValueError('unsupported_attribute')
            if key=='data-code' and (tag!='div' or not isinstance(value,str) or not re.fullmatch(r'(?:ltBlock[0-9]{1,12}|b-[0-9a-f]{5})',value)):raise ValueError('unsupported_attribute')
            if key in ('data-editable','data-main-class','data-param') and (tag!='div' or value not in (('true',) if key=='data-editable' else ('header','text'))):raise ValueError('unsupported_attribute')
            if key=='id' and (not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',value)):raise ValueError('unsupported_attribute')
            if key=='color' and (tag!='font' or not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value)):raise ValueError('unsupported_attribute')
            if key=='face' and (tag!='font' or not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9, -]{1,100}',value)):raise ValueError('unsupported_attribute')
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


def strip_obsolete_manager_paragraphs(source):
    """Remove the two exact obsolete manager instructions from reviewed HTML."""
    if not isinstance(source,str) or not source:raise ValueError('invalid_html')
    starts=[0]+[i+1 for i,c in enumerate(source) if c=='\n']
    class Paragraphs(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.current=None
            self.ranges=[]
        def pos(self):
            line,col=self.getpos();return starts[line-1]+col
        def handle_starttag(self,tag,attrs):
            if tag=='p':
                if self.current is not None:raise ValueError('nested_paragraph')
                self.current=[self.pos(),[]]
        def handle_data(self,data):
            if self.current is not None:self.current[1].append(data)
        def handle_endtag(self,tag):
            if tag=='p' and self.current is not None:
                end=self.pos();close=re.match(r'</\s*p\s*>',source[end:],re.I)
                if not close:raise ValueError('invalid_paragraph')
                text=' '.join(' '.join(self.current[1]).split())
                if re.fullmatch(r'Для приобретения данного пакета(?: обучения)?, обратитесь к менеджеру по оплате\.',text,re.I):
                    self.ranges.append(('manager',self.current[0],end+len(close.group(0))))
                elif text=='Это можно сделать прямо из вашего личного кабинета через мессенджер (кнопки для связи в правом нижнем углу: чат и телеграмм).':
                    self.ranges.append(('old_contact',self.current[0],end+len(close.group(0))))
                self.current=None
    parser=Paragraphs();parser.feed(source);parser.close()
    if parser.current is not None or sorted(k for k,_,_ in parser.ranges)!=['manager','old_contact']:
        raise ValueError('manager_paragraphs_unconfirmed')
    result=source
    for _,start,end in reversed(parser.ranges):result=result[:start]+result[end:]
    return result


def strip_empty_answer_form(source):
    """Remove exactly one empty known answer form, preserving all other bytes."""
    if not isinstance(source,str) or not source:raise ValueError('invalid_html')
    starts=[0]+[i+1 for i,c in enumerate(source) if c=='\n']
    class Form(HTMLParser):
        def __init__(self):super().__init__(convert_charrefs=True);self.stack=[];self.start=None;self.end=None;self.classes=set();self.div_count=0
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
                self.div_count+=1
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
    known_classes=(parser.classes=={'answer-form','answer-form-content','answer-textarea-container'}
                   or (parser.classes=={'answer-form'} and parser.div_count==1))
    if parser.stack or parser.start is None or parser.end is None or not known_classes:
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
