"""Hash-bound MailerLite fragments: retain material, simplify legacy mail layout.

No HTML/JS execution, fetching or private source literals. Original source must
remain with the caller. Images are handed to the existing verified asset path.
"""
import copy
import hashlib
from html import escape, unescape
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit, urlunsplit

from importer import ACCOUNT, ORIGIN, Review
from normalize_inline_images import Element, Document, _probe
from normalize_legacy_html_decorations import _has_content_style
from normalize_remaining_static_material import _number, _node_at

CODE = 'reviewed_email_html_normalized'
LAYOUT_CODE = 'legacy_layout_simplified'
UPGRADE_CODE = 'reviewed_email_image_https_upgrade'
APPROVED = {
    (105,1539): ((0,), 'd1c6a0c03f7d28271c02004684603fd5e1c6687a7f87aaa1982f81d5a1b6a9e4'),
    (105,1543): ((0,), '64cc03380d156a0346f0dc1b196da7c8bacef6463b5a73f1d70569d2a1af1a2b'),
    (480,4614): ((0,), '9c687fa6c647cef24a5910d535a00318ed3de6a1fc145fe6e7653a49396f24a6'),
    (481,4620): ((0,), 'ca272b97d323c3b0c8f4b05444e8f93e48fbbf68593091974bf8e479f5ec802b'),
    (482,4626): ((0,), 'bed4738f901cb3f33db1397fc97c2909fefb1d566e006d88e9318f6f1ed50370'),
}
KNOWN_AUXILIARY = {
    ('link','bfdc01974cfcddb735bb0e9ff0b8d2a0ef0a65163cef8ccf3bd59e1f3aa632e8'),
    ('link','cbdbfcdc1c5199e150bdbdfe5671bd28f2f72eeff22e055ed766b0f10a608cec'),
    ('meta','096691b168721961c9be22725b5a21e84491441998f75be4c6e580fd7287d4cb'),
    ('meta','17c594a43d45b28c52fe4454f8763fda2583aa4a84029f691f19dbaac7207307'),
    ('meta','53f34722103c5f59e8f2b6764c5fbc2487674db3ba86b0ca7bb8da776f9e96ef'),
    ('meta','5816680d60f035099a8d44715086869ad9ffc21600095b3a2ffcef92660a890a'),
    ('meta','5ca80abe1f25cd9c4760816222ebac23cb59933c3ae15f2e70525e981157346d'),
    ('meta','c2b90ec2a708afb91e9c50dd8961edbfaf9a2a5cfcd1e62708c18195845428cd'),
    ('meta','e8b1da1d00bc0048adc9b86c66d584e643db93846d196f504987b384fab5f7ad'),
    ('meta','fd88af21532adf873a2391adbb7f52ec1d7d56d5240cc77ec10354ed5ff43c62'),
    ('script','3b257be171887231c24a8230526f663191fc59f33e412804b88246828165d647'),
    ('script','cd98d5f0021428087eeab6b2d012328b17f0c48bc528f723fb92601db74aae4f'),
    ('script','dc1f60e9bffe4db8b504924b91dcce26630d51f11e7cfaf07418824b952658f1'),
    ('script','e349b1a364fe00d40f2a621a0d1acd09e43eade10c15ee98c9240c1fc9cadc3e'),
    ('style','61eb23429adc55f7ca3e6c03fe4c4d998b7f8828189b7f2effbfacf200397276'),
    ('style','6d19bb2f6f2df0c056a1836c720982cd7d2a9e6a6e71372831f03fef1197a6a3'),
    ('title','eb5c0bb70e7ef0fd459c341113a30129285ad2983bd3061438d7f2117f3f0f1f'),
}
# Both files were independently fetched anonymously with NoRedirect, bounded
# decoding and Pillow. Source/cached byte hashes are not source URLs.
ASSETS = {
    'background': {'original_url_sha256':'28a67573ba45c801804620323a163d7a7d089cff3ab70889d66691a216a68dc3',
        'transport_url_sha256':'28a67573ba45c801804620323a163d7a7d089cff3ab70889d66691a216a68dc3',
        'content_sha256':'81ce299347e7dde15488b05508ede874d41bf004d7e124c653e6004a505fd244','size':28867},
    'body_image': {'original_url_sha256':'9081a405b2fd863709390fe7bf064c19c18b1db612999245ac964a0ec08d9d5b',
        'transport_url_sha256':'73dd43ddbdff4eb06c92c9e19b7facd6a4f5e54c8e6dd0d03c89cefa33038d7e',
        'content_sha256':'044219fdc9ccccdf314ec9a053f9d76b7cc79e07861fdd1df667d7f05d7ebc62','size':19273},
}
AUX = {'meta','title','link','script','style'}
VOID = {'meta','link','img','br','hr','input','col','source','wbr'}
CLASSES = {'mlTemplateContainer','mlEmailContainer','mlContentTable'}
# Reviewed Outlook/Office settings and conditional font fallbacks. No material
# URLs or lesson text occur in these five identical legacy mail comments.
KNOWN_COMMENTS = {
    '2d3cc1dcef2d08bad575b4c828d70e97115dbbaaf2c8c449bd4ef43a85ead872',
    'b84e3e75a44e80200de1b762305700d1066cd1f987fb7daaafc688896652c206',
    'd1f342fac71569b02153277754580b0dff754dde23fdaabb31c7374dbeb08b64',
    'f29a3ae60703135f68d252d61d9d2892e1352e703eeea647c5df6cd6a3128926',
    '8935217185a7090934cfd81dc18f1cd0c1ef323b3e495430b1221da1a4ed57bc',
}


def _sha(text): return hashlib.sha256(text.encode('utf-8')).hexdigest()
def _review(): raise Review('reviewed_email_html_requires_review')


class _Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.source=source; self.lines=[0]+[i+1 for i,c in enumerate(source) if c=='\n']
        self.root=Element(); self.stack=[self.root]; self.nodes=[];self.comments=[]
        self.feed(source); self.close()
        if len(self.stack)!=1: _review()

    def position(self):
        row,col=self.getpos(); return self.lines[row-1]+col

    def handle_starttag(self, tag, attrs):
        if len(self.nodes)>10000 or len(self.stack)>64 or len(attrs)!=len(dict(attrs)) or any(k.startswith('on') for k,v in attrs): _review()
        node=Element(tag,attrs,self.get_starttag_text());node.start=self.position();node.end=node.start+len(node.opening)
        self.stack[-1].children.append(node);self.nodes.append(node)
        if tag not in VOID:self.stack.append(node)

    def handle_startendtag(self,tag,attrs):
        if tag not in VOID:_review()
        self.handle_starttag(tag,attrs)

    def handle_endtag(self,tag):
        if tag in VOID or len(self.stack)==1 or self.stack[-1].tag!=tag:_review()
        start=self.position();match=re.match(r'</\s*'+tag+r'\s*>',self.source[start:],re.I)
        if not match:_review()
        node=self.stack.pop();node.closing=match[0];node.end=start+len(match[0])

    def handle_data(self,value):self.stack[-1].children.append(value)
    def handle_entityref(self,name):self.handle_data('&'+name+';')
    def handle_charref(self,name):self.handle_data('&#'+name+';')
    def handle_comment(self,value):
        start=self.position();end=self.source.find('-->',start)
        if end<0:_review()
        digest=_sha(self.source[start:end+3])
        if digest not in KNOWN_COMMENTS:_review()
        self.comments.append(digest)
    def handle_decl(self,value):_review()
    handle_pi=handle_decl
    unknown_decl=handle_decl

    def auxiliary_hashes(self):
        return [(n.tag,_sha(self.source[n.start:n.end])) for n in self.nodes if n.tag in AUX]


def _transport(source,role,already_upgraded=False):
    if not isinstance(source,str):_review()
    receipt=ASSETS[role];digest=_sha(source)
    expected=receipt['transport_url_sha256'] if already_upgraded else receipt['original_url_sha256']
    if digest!=expected:_review()
    url=urlsplit(source)
    if url.scheme not in {'http','https'} or not url.hostname or url.username is not None or url.password is not None or url.port is not None or url.query or url.fragment:_review()
    target=urlunsplit(('https',url.netloc,url.path,'',''))
    if _sha(target)!=receipt['transport_url_sha256']:_review()
    return target


def _material(source,upgraded=False):
    document=_Document(source);text=[];links=[];images=[]
    def visit(node):
        if isinstance(node,str):text.append(unescape(node));return
        if node.tag in AUX:return
        if node.attrs.get('id')=='fb-root':
            if any(isinstance(c,Element) or unescape(c).strip() for c in node.children):_review()
            return
        if node.tag=='a':links.append(tuple(sorted((k,v) for k,v in node.attrs.items() if k!='style')))
        if node.tag=='img':images.append(_transport(node.attrs.get('src'),'body_image',upgraded))
        for child in node.children:visit(child)
    visit(document.root)
    return ''.join(text),links,images


def _portable(css,tag,validate,stats,backgrounds):
    result={};borders={};seen=set()
    for index,piece in enumerate(css.split(';')):
        piece=piece.strip()
        if not piece:continue
        if ':' not in piece:
            if tag=='table' and index==0 and piece==')':stats['invalid_legacy_css_prefix']+=1;continue
            _review()
        key,value=(part.strip() for part in piece.split(':',1));key=key.lower()
        if key in seen:_review()
        seen.add(key)
        if key=='background-image':
            match=re.fullmatch(r'url\(([\"\'])([^\"\']+)\1\)',value)
            if tag!='table' or not match:_review()
            backgrounds.append(_transport(match[2],'background'));stats['background_images_linearized']+=1;continue
        if key in {'mso-table-lspace','mso-table-rspace'} and value=='0pt' or key in {'-ms-text-size-adjust','-webkit-text-size-adjust'} and value=='100%':
            stats['mail_client_css_controls']+=1;continue
        if ((key=='border-radius' and value=='4px') or (key=='display' and value=='inline-block')
                or (key=='height' and value=='auto') or (key=='min-width' and re.fullmatch(r'(?:125|600)px',value))):
            stats['layout_css_controls_simplified']+=1;continue
        if key in {'border-style','border-color','border-width'}:
            borders[key.split('-')[1]]=value;continue
        if key=='word-break' and value=='break-word':key='overflow-wrap';stats['word_wrap_mapped']+=1
        result[key]=value
    if borders:
        if set(borders)!={'style','color','width'} or borders['style']!='solid':_review()
        widths=borders['width'].split()
        if not 1<=len(widths)<=4 or any(not re.fullmatch(r'[0-9]{1,2}px',v) for v in widths):_review()
        if len(widths)==1:widths*=4
        elif len(widths)==2:widths*=2
        elif len(widths)==3:widths.append(widths[1])
        for edge,width in zip(('top','right','bottom','left'),widths):result['border-'+edge]=width+' solid '+borders['color']
        stats['border_shorthands_expanded']+=1
    if tag=='p':result={'font-family':'Arial,sans-serif','font-size':'16px','color':'#303030',**result}
    color=re.sub(r'\s+','',result.get('color','')).lower()
    if color in {'white','#fff','#ffffff','rgb(255,255,255)'}:
        bg=re.sub(r'\s+','',result.get('background',result.get('background-color',''))).lower()
        if tag!='a' or bg in {'','none','transparent','white','#fff','#ffffff','rgb(255,255,255)'}:_review()
    cleaned=';'.join(k+':'+v for k,v in result.items())
    if cleaned:validate('<span style="'+escape(cleaned,quote=True)+'"></span>')
    return cleaned


def _clean(source,validate):
    document=_Document(source);aux=document.auxiliary_hashes()
    if len(aux)!=len(KNOWN_AUXILIARY) or set(aux)!=KNOWN_AUXILIARY:_review()
    for node in document.nodes:
        if node.tag=='title' and any(isinstance(c,Element) or unescape(c).strip() for c in node.children):_review()
    tables=[n for n in document.nodes if n.tag=='table']
    if len(tables)!=4:_review()
    def significant(node):return [c for c in node.children if isinstance(c,Element) or unescape(c).strip()]
    for table in tables:
        items=significant(table)
        if len(items)!=1 or not isinstance(items[0],Element) or items[0].tag!='tbody':_review()
        items=significant(items[0])
        if len(items)!=1 or not isinstance(items[0],Element) or items[0].tag!='tr':_review()
        items=significant(items[0])
        if len(items)!=1 or not isinstance(items[0],Element) or items[0].tag!='td':_review()
    stats={k:0 for k in ('invalid_legacy_css_prefix','background_images_linearized','mail_client_css_controls','layout_css_controls_simplified','border_shorthands_expanded','word_wrap_mapped','empty_preview_nodes_removed')};backgrounds=[]
    def emit(node):
        if isinstance(node,str):return node
        tag=node.tag;values=dict(node.attrs)
        if tag in AUX:return ''
        if values.get('id')=='fb-root':
            if tag!='div' or values!={'id':'fb-root','style':'display:none'} or significant(node):_review()
            stats['empty_preview_nodes_removed']+=1;return ''
        if tag not in validate.__globals__['TAGS']|{'img'} or tag=='style':_review()
        if tag in {'table','tbody','tr','td'}:
            allowed={'style','align','class'}|({'bgcolor','border','cellpadding','cellspacing','width','id'} if tag=='table' else set())
            if set(values)-allowed:_review()
            if set(values.get('class','').split())-CLASSES:_review()
            if 'id' in values and not re.fullmatch('ml-block-[0-9]{1,12}',values['id']):_review()
            if values.get('align') not in (None,'center'):_review()
            if any(values.get(k) not in (None,'0') for k in ('border','cellpadding','cellspacing')):_review()
            if values.get('width') not in (None,'600','100%') or values.get('bgcolor') not in (None,'#ffffff'):_review()
            css=values.get('style','')
            if values.get('align'):css+=';text-align:center'
            if values.get('bgcolor'):css+=';background-color:'+values['bgcolor']
            if tag=='table':css+=';max-width:640px' if values.get('class')=='mlEmailContainer' else ''
            css=_portable(css,tag,validate,stats,backgrounds)
            # Fixed mail widths become one responsive, readable column.
            if values.get('width'):css=re.sub(r'(?:^|;)width:[^;]*','',css)+';width:100%'
            values={'style':css.strip(';')} if css.strip(';') else {};tag='div'
        else:
            if tag=='img':
                values['src']=_transport(values.get('src'),'body_image')
                # The existing image splitter validates its own size/style
                # grammar and records sizing; do not turn it into text CSS.
            else:
                css=_portable(values.get('style',''),tag,validate,stats,backgrounds)
                if css:values['style']=css
                else:values.pop('style',None)
        opening='<'+tag+''.join(' '+k+('' if v is None else '="'+escape(v,quote=True)+'"') for k,v in values.items())+'>'
        return opening+''.join(emit(c) for c in node.children)+('' if tag in VOID else '</'+tag+'>')
    cleaned=''.join(emit(c) for c in document.root.children)
    if len(backgrounds)!=1:_review()
    probe=Document(cleaned);validate(_probe(probe.root))
    if len(probe.images)!=1 or _material(source)!=_material(cleaned,upgraded=True):
        raise Review('reviewed_email_material_mismatch')
    return cleaned,backgrounds[0],aux+[('comment',value) for value in document.comments],stats


def normalize_reviewed_email_html(ape,course_id,lesson_id,validate_static):
    if (ACCOUNT,ORIGIN)!=('mastervision','https://shop.mastervision.su'):
        raise Review('reviewed_email_account_mismatch')
    if not isinstance(ape,dict) or ape.get('name')!='page' or not callable(validate_static):
        raise Review('reviewed_email_source_invalid')
    copied=copy.deepcopy(ape);approved=APPROVED.get((_number(course_id),_number(lesson_id)))
    if approved is None:return copied,[]
    path,digest=approved;node=_node_at(copied,path)
    if (not isinstance(node,dict) or node.get('name')!='text' or node.get('children',[])!=[]
            or not isinstance(node.get('fields'),dict) or set(node['fields'])-{'html','anchor'}
            or node['fields'].get('anchor') not in (None,'') or _has_content_style(node.get('style'))
            or set(node)-{'id','name','fields','children','style'}):return copied,[]
    html=node['fields'].get('html')
    if not isinstance(html,str) or len(html)>200000:return copied,[]
    try:actual_digest=_sha(html)
    except UnicodeError:raise Review('reviewed_email_source_invalid') from None
    if actual_digest!=digest:return copied,[]
    try:cleaned,background,aux,stats=_clean(html,validate_static)
    except (ValueError,UnicodeError,RecursionError):_review()
    prefix='mve_'+_sha(str(path)+digest)[:48]
    occupied=set();pending=[(copied,0)];count=0
    while pending:
        item,depth=pending.pop();count+=1
        if (count>150000 or depth>100 or not isinstance(item,dict) or not isinstance(item.get('name'),str)
                or not isinstance(item.get('fields',{}),dict) or not isinstance(item.get('children',[]),list)):
            raise Review('reviewed_email_source_invalid')
        if isinstance(item.get('id'),str):occupied.add(item['id'])
        pending.extend((child,depth+1) for child in item.get('children',[]))
    ids=(prefix+'_b',prefix+'_t')
    if set(ids)&occupied:raise Review('reviewed_email_source_invalid')
    node.update(name='section',fields={},children=[
        {'name':'image','id':ids[0],'fields':{'anchor':'','imageSrc':background}},
        {'name':'text','id':ids[1],'fields':{'html':cleaned}}])
    changes=[{'path':list(path),'code':CODE,'source_html_sha256':digest,'result_html_sha256':_sha(cleaned),
              'auxiliary_elements':[{'tag':tag,'source_sha256':value} for tag,value in aux],
              'image_expectations':copy.deepcopy(ASSETS),'material_signature_preserved':True},
             {'path':list(path),'code':LAYOUT_CODE,'single_cell_tables':4,**stats},
             {'path':list(path),'code':UPGRADE_CODE,'original_url_sha256':ASSETS['body_image']['original_url_sha256'],
              'transport_url_sha256':ASSETS['body_image']['transport_url_sha256']}]
    return copied,changes
