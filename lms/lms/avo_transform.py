"""Pure, conservative AVO lesson-to-EditorJS conversion; no I/O or execution."""
from html import escape
from html.parser import HTMLParser
import hashlib
import base64
import json
import math
import re
from urllib.parse import parse_qs, urlsplit
from lms.lms.avo_html_fragment import make_html_block, strip_empty_answer_form, split_reviewed_audio_links

MAX_BYTES = 16 * 1024 * 1024
MAX_DEPTH = 100
MAX_NODES = 150000  # JSON values, not lesson blocks; APE blocks remain capped separately.
MAX_BLOCKS = 1000
ACCOUNT = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
IMAGE_KEY = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")
PLACEHOLDER_IMAGE_SHA256 = '44c98968db4973a119db3bbc00ca36392c1466e1b631596e1fff0ac4a2474ea2'
PRIVATE_FILE = re.compile(r"^/private/files/[a-zA-Z0-9][a-zA-Z0-9_.-]{0,180}$")
ALLOWED_TAGS = {"p", "br", "strong", "b", "em", "i", "u", "s", "a", "ul", "ol", "li",
                "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "code"}

# Explicit owner decision: use only the second of two concatenated YouTube
# links in this exact source field. A changed source digest requires review.
# The original complete field remains in the private source snapshot.
CONFIRMED_CONCATENATED_YOUTUBE = {
    ('mv-centr', '19', '62'): '6c6f238d72d0cc9b3f85a2296c57456c8b0108de257af8ab497b8a7a2634e5b9',
}
# The owner explicitly requested a single-column sequence for these lessons.
CONFIRMED_SINGLE_COLUMN_LESSONS = {('mv-centr', '117', '571'), ('mv-centr', '118', '587')}
# Owner approved flattening only this exact image-and-text section.
CONFIRMED_SINGLE_COLUMN_SECTIONS = {('mv-centr','258','1150'):
    '65769313d05a3037d67800d78caeb764452be7e932a96fe040df4bae1c67d625'}
CONFIRMED_HTML_FIELDS = {('mv-centr','258','1151'):
    'bd34b4023517d1f359d4c81aabf15d728845cd4f318e9ea7d629f017887a2d5d',
    ('mv-centr','447','2608'):'40c2aefc41caa2cde7ac583ff753e3eeba135257f2b1e6782fea1e573a63415d'}
CONFIRMED_OMIT_HEADERS = {('mv-centr','447','2608'):
    'fcc9b9dfb972f67fa3e47b266af9ad5345f3e5593aa2a9f9b7163181c4ac16bf'}
CONFIRMED_OMIT_EMPTY_BUTTONS = {('mv-centr','952','9422'):
    '14eb83aff8cbadebc98291cf587459e2ccda9b646b0a0fcc6c4ccc5c85feab9f'}
# The owner selected content for these exact MV-Centr captures. If a capture
# changes, do not apply the decision to the new contents without review.
REVIEWED_SELECTIONS = {
    ('mv-centr','958','9497'): ('f322cbf9b57f4e63cc6ebd0d1fa858a966d30a721a72cef5fc6965df46882abf','videos',0),
    ('mv-centr','889','8584'): ('dfc6bd4cfbb0481dc6c9d99e38951a43ccd59f24d00aa4515ecf912c187c3341','videos',6),
    ('mv-centr','951','9401'): ('54a8b35b7ebabbee601cce7d601283899c85f9c72e972af564b7c49cf372a8b1','videos',2),
    ('mv-centr','952','9416'): ('41ff6d97b59feb28328daa4769c55a3fc8d21b958a19b532aa02886d8bc0e9cc','videos',2),
    ('mv-centr','954','9448'): ('ccb24d5ba6d6cd77c07c38751b2dc5e804f8652923f1ff268791d4329449427a','videos',2),
    ('mv-centr','960','9508'): ('e3693219b6858434f1b15407074a0f2489c4bac001bc615279aed6e1434f7ed1','videos',2),
    ('mv-centr','961','9511'): ('2a8aa37979632bc0e63ef95d0b03246333b1037f7088945748e6b34a4c714273','videos',2),
    ('mv-centr','953','9434'): ('d088c6c2af205316f2f705c34ecdd932f483559c8299db710a8fc6d8f9d00e78','videos',4),
    ('mv-centr','959','9500'): ('734ec85ef66519977a499062b46816ea82c713b91f46d120e4dd39f1e28d9f25','videos',4),
    ('mv-centr','955','9474'): ('5a6ee7d4d24cd3675ff982763c875c3e99b0ac96b42d841c8f673cc5017f84b5','videos',1),
    ('mv-centr','958','9496'): ('79e33d73346391e8940123a6f0921c510e992571fc90c57ba714a8b367275a90','videos',0),
    ('mv-centr','899','8699'): ('d0142121f66f647b08af1124424bdd88528c350e686526d149a33966eaa87194','placeholder',0),
    ('mv-centr','893','8621'): ('f0f0dd08db2fc79204a9e812610df544d3f26bd9badc36edfb31cf5407381253','placeholder',0),
    ('mv-centr','899','8651'): ('0164750455a3ad1ce304adc9696fd7ed6d16db55e2acc2c71a53e912746fa890','welcome',0),
    ('mv-centr','896','8627'): ('b1e12c28b0e256f11b33d1b381ba12336cb43149c4caa872b452514efded2eee','videos',0),
    ('mv-centr','895','8624'): ('08892c679345238213fd0159861fa0cff65ce9ddfa7c1e1611d4ce0fb14cb73e','videos',0),
    ('mv-centr','892','8610'): ('afef3165d49134c1203f8a6bf17ec6386bd1bddcf068f74840168153159b5d6b','videos',0),
    ('mv-centr','894','8617'): ('44f867c6bc8e4f8ab40a3acfeb49761b6872efcd26175b87200eb882d2843ab6','videos',1),
    ('mv-centr','893','8648'): ('1bb9b4b0483d807ec94c0864e5bba16baaf6e59e8df561ad3a16ac8634c3eaf2','videos',0),
    ('mv-centr','891','8609'): ('1bb9b4b0483d807ec94c0864e5bba16baaf6e59e8df561ad3a16ac8634c3eaf2','videos',0),
    ('mv-centr','890','8607'): ('9190f4e80e8426962208170a9970ebbec723baf1f7b438832bb9e5de199aeaee','videos',0),
    ('mv-centr','889','8579'): ('0e665433a4414fff819b4255278f7abd8b95d0c49dc3907d27c68bfd1d0c3fe2','videos',4),
}

def reviewed_selection(root, account, course, lesson):
    rule = REVIEWED_SELECTIONS.get((str(account),str(course),str(lesson)))
    if not rule: return None
    digest = _sha256_text(json.dumps(root,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False))
    return rule[1:] if digest == rule[0] else None
# Explicit user decision for these exact snapshots: keep the assignment text
# and omit the empty answer form for now. The original remains in the snapshot.
CONFIRMED_TEXT_ONLY_ANSWER_FORMS = {
    ('mv-centr', '25', '115'): '402edcfd7b360ce9d6c9b8c628457be2f7a14ad10e482601b43bb89ab851a53f',
    ('mv-centr', '101', '464'): '9c36aafe11bc53c2562516276fbd033ec77af4b736dfccb60b60e17b264f1368',
}
# Owner requested replacing these particular legacy players with links.
# Digests bind the decision to the verified source; originals remain private.
CONFIRMED_DRIVE_AUDIO_LINKS = {
    ('mv-centr', '234', '3866'): 'eadc8b61117adff696aa922db97a05e2bc02482d4a64c11b4c01a2fd9613b2dc',
    ('mv-centr', '234', '4030'): 'c031903da0b8e7b31f19ea6dd98cfad00fb9b1808e0ce10eef89e94c8a137029',
    ('mv-centr', '234', '3872'): '06418e87139fc880a981d57cae41c7490a3ebccfaf57cb628b4d24a1d25b6d91',
    ('mv-centr', '236', '5724'): '983fbb61980d849d89f02869f11ecbef95a872cd92bd3199975ad4490407d63b',
    ('mv-centr', '236', '4468'): '365b89e868707f504cfccf8f810feaef856924d2e189152a280069825ea41ef3',
    ('mv-centr', '237', '7315'): 'd0d11f9427e8c29120a558da516c6e7caf664aabba5fedae41e2f4a4695cb2ec',
}


def _sha256_text(value):
    if not isinstance(value,str):return None
    try:return hashlib.sha256(value.encode('utf-8')).hexdigest()
    except UnicodeError:return None


def omit_placeholder_section(node, account, course, lesson):
    """Omit only the owner's exact decorative image and generic greeting."""
    # This lesson was imported before the owner decision; keep idempotent checks
    # for its existing draft until it is separately updated.
    if (str(account),str(course),str(lesson))==('mv-centr','258','1150'):return False
    if not isinstance(node,dict) or node.get('name')!='section':return False
    cols=node.get('children')
    if not isinstance(cols,list) or len(cols)!=2 or any(not isinstance(c,dict) or c.get('name')!='column' for c in cols):return False
    expected_overlay={'enabled':False,'r':255,'g':255,'b':255,'a':0.6}
    for item in [node]+cols:
        fields=item.get('fields',{})
        if not isinstance(fields,dict) or any(k!='backgroundOverlayColor' for k in fields):return False
        if fields.get('backgroundOverlayColor') not in (None,'',False,{},expected_overlay):return False
    parts=[c.get('children') for c in cols]
    if any(not isinstance(p,list) or len(p)!=1 or not isinstance(p[0],dict) for p in parts):return False
    image,text=parts[0][0],parts[1][0]
    for item in [node]+cols+[image,text]:
        if any(value not in (None,'',False,[],{}) for key,value in item.items()
               if key not in ('id','name','fields','children','style')):return False
    if image.get('name')!='image' or text.get('name')!='text' or image.get('children',[]) or text.get('children',[]):return False
    a,b=image.get('fields'),text.get('fields')
    if not isinstance(a,dict) or not isinstance(b,dict) or set(a)-{'anchor','imageSrc'} or set(b)-{'anchor','html'}:return False
    return (a.get('anchor') in ('',None) and b.get('anchor') in ('',None)
            and _sha256_text(a.get('imageSrc'))==PLACEHOLDER_IMAGE_SHA256
            and b.get('html')=='<p>Здравствуйте, {name}</p>')


def omit_placeholder_node(node, account, course, lesson):
    if (str(account),str(course),str(lesson))==('mv-centr','258','1150'):return False
    if not isinstance(node,dict) or node.get('children',[]):return False
    if any(value not in (None,'',False,[],{}) for key,value in node.items()
           if key not in ('id','name','fields','children','style')):return False
    fields=node.get('fields')
    if not isinstance(fields,dict) or fields.get('anchor') not in ('',None):return False
    if node.get('name')=='image':
        return not (set(fields)-{'anchor','imageSrc'}) and _sha256_text(fields.get('imageSrc'))==PLACEHOLDER_IMAGE_SHA256
    if node.get('name')=='text':
        return not (set(fields)-{'anchor','html'}) and fields.get('html')=='<p>Здравствуйте, {name}</p>'
    return False


def _ape_spacer(node):
    """Recognize a static separator only when every unrendered setting is default."""
    fields = node.get('fields')
    if not isinstance(fields, dict) or fields.get('anchor') not in ('', None):
        raise ValueError('unsupported_spacer')
    if fields.get('html') not in (None, '', 'Разделитель') or set(fields) - {'anchor', 'html'}:
        raise ValueError('unsupported_spacer')
    style = node.get('style')
    if not isinstance(style, dict) or set(style) != {'lists'} or not isinstance(style['lists'], dict):
        raise ValueError('unsupported_spacer')
    lists = style['lists']
    block = {'display': {'value': {'visible': 'block'}}}
    content = {'justifyContent': {'value': {'type': 'center'}}}
    radius = {f'border{corner}Radius': {'value': {'number': 0, 'units': 'px'}}
              for corner in ('TopLeft', 'TopRight', 'BottomLeft', 'BottomRight')}
    overlay = {'backgroundColor': {'value': {'enabled': False, 'r': 255, 'g': 255, 'b': 255, 'a': 0.6}}, **radius}
    if lists.get('block') != block or lists.get('content') != content or lists.get('overlay') != overlay:
        raise ValueError('unsupported_spacer')
    for key, value in lists.items():
        if key in ('block', 'content', 'overlay', 'spacer'):
            continue
        match = re.fullmatch(r'\$__max_width__\d+__(block|content|overlay|spacer)', key)
        if not match or value != lists.get(match.group(1)):
            raise ValueError('unsupported_spacer')
    value = lists.get('spacer')
    if not isinstance(value, dict):
        raise ValueError('unsupported_spacer')
    try:
        def dimension(key, units, maximum):
            raw = value[key]['value']
            number = raw['number']
            if (set(raw) != {'number', 'type', 'units'} or raw['type'] != 'fixed' or raw['units'] != units
                    or type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number <= maximum):
                raise ValueError('unsupported_spacer')
            return number
        height, width = dimension('height', 'px', 500), dimension('width', '%', 100)
        top, bottom = dimension('marginTop', 'px', 500), dimension('marginBottom', 'px', 500)
        colour = value['backgroundColor']['value']
        if (set(colour) != {'enabled', 'r', 'g', 'b', 'a'} or colour['enabled'] is not True or colour['a'] != 1
                or any(type(colour[k]) is not int or not 0 <= colour[k] <= 255 for k in ('r', 'g', 'b'))):
            raise ValueError('unsupported_spacer')
        expected = {'backgroundColor': {'value': colour}, **radius,
            **{f'border{side}Width': {'value': {'number': 0, 'type': 'fixed', 'units': 'px'}} for side in ('Top','Right','Bottom','Left')},
            'borderStyle': {'value': {'type': 'solid'}},
            **{f'border{side}Color': {'value': {'enabled': True, 'r': 0, 'g': 0, 'b': 0, 'a': 1}} for side in ('Top','Right','Bottom','Left')},
            'opacity': {'value': {'number': 1}}, 'backgroundImage': {'value': {'url': ''}},
            'backgroundSize': {'value': {'width': 100, 'type': 'auto', 'units': '%'}},
            'backgroundRepeat': {'value': {'type': 'repeat'}}, 'backgroundAttachment': {'value': {'type': 'scroll'}},
            'backgroundPosition': {'value': {'type': 'left-top'}}, '#__maskImage__after': {'value': {'url': ''}},
            '#__maskSize__after': {'value': {'width': 100, 'type': 'auto', 'units': '%'}},
            '#__maskRepeat__after': {'value': {'type': 'repeat'}}, '#__maskPosition__after': {'value': {'type': 'left-top'}},
            '#__backgroundColor__after': {'value': {'enabled': True, 'r': 0, 'g': 0, 'b': 0, 'a': 1}}}
        for key in ('height', 'width', 'marginTop', 'marginBottom'):
            expected[key] = value[key]
        for key in ('marginLeft', 'marginRight'):
            expected[key] = {'value': {'number': 0, 'type': 'fixed', 'units': 'px'}}
        if value != expected:
            raise ValueError('unsupported_spacer')
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError('unsupported_spacer') from exc
    return {'height': height, 'width': width, 'marginTop': top, 'marginBottom': bottom,
            'color': '#%02x%02x%02x' % (colour['r'], colour['g'], colour['b'])}


def _bounded(value):
    """Validate JSON sizes before visiting content, including nested structures."""
    try:
        raw = json.dumps(value, ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("invalid_json") from exc
    if len(raw) > MAX_BYTES:
        raise ValueError("input_too_large")
    stack, seen = [(value, 0)], 0
    while stack:
        node, depth = stack.pop()
        seen += 1
        if depth > MAX_DEPTH or seen > MAX_NODES:
            raise ValueError("input_structure_limit")
        if isinstance(node, dict):
            stack.extend((v, depth + 1) for v in node.values())
        elif isinstance(node, list):
            stack.extend((v, depth + 1) for v in node)


def _id(value):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,14}", value):
        raise ValueError("invalid_source_id")
    return value


def _url(value, providers=None):
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) <= 32 or ord(c) == 127 or c == "\\" for c in value):
        return False
    try:
        u = urlsplit(value)
        if u.scheme not in ("https", "http") or not u.hostname or u.username or u.password:
            return False
        if u.port not in (None, 80, 443):
            return False
        if providers and (u.scheme != "https" or u.port is not None or u.hostname.lower() not in providers):
            return False
        return True
    except ValueError:
        return False


def _player_url(value, provider):
    domains = {"youtube": {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com"},
               "rutube": {"rutube.ru", "www.rutube.ru"}}
    if not _url(value, domains[provider]):
        return False
    u = urlsplit(value)
    query = parse_qs(u.query, keep_blank_values=True)
    if provider == "youtube":
        host = u.hostname.lower()
        if host == "youtu.be":
            match = re.fullmatch(r"/([A-Za-z0-9_-]{11})/?", u.path)
        elif host in ("youtube-nocookie.com", "www.youtube-nocookie.com"):
            match = re.fullmatch(r"/embed/([A-Za-z0-9_-]{11})/?", u.path)
        elif u.path == "/watch":
            return len(query.get("v", [])) == 1 and bool(re.fullmatch(r"[A-Za-z0-9_-]{11}", query["v"][0]))
        else:
            match = re.fullmatch(r"/(?:embed|shorts|v)/([A-Za-z0-9_-]{11})/?", u.path)
        return bool(match)
    match = re.fullmatch(r"/(?:video/(private/)?|play/embed/)([a-fA-F0-9]{32})/?", u.path)
    keys = query.get("p", [])
    return bool(match and len(keys) <= 1 and (not match.group(1) or bool(keys and keys[0]))
                and (not keys or re.fullmatch(r"[A-Za-z0-9_-]+", keys[0])))


class _SafeHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.ok = True
        self.stack = []

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED_TAGS:
            self.ok = False
        if tag != "br":
            self.stack.append(tag)
        seen = set()
        for key, value in attrs:
            if key in seen or tag != "a" or key not in ("href", "title", "target", "rel"):
                self.ok = False
            seen.add(key)
            if key == "href" and not _url(value):
                self.ok = False
            if key == 'target' and value not in ('_blank','_self'):
                self.ok = False
            if key == 'rel' and (not isinstance(value,str) or not set(value.split()).issubset({'noopener','noreferrer','nofollow'})):
                self.ok = False

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag != "br" and self.stack:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag == "br":
            return
        if not self.stack or self.stack.pop() != tag:
            self.ok = False

    def handle_comment(self, data):
        self.ok = False

    def unknown_decl(self, data):
        self.ok = False

    def handle_decl(self, decl):
        self.ok = False

    def handle_pi(self, data):
        self.ok = False


def _safe_html(value):
    if not isinstance(value, str):
        return False
    try:
        parser = _SafeHTML()
        parser.feed(value)
        parser.close()
        return parser.ok and not parser.stack
    except (ValueError, RecursionError):
        return False


def _safe_heading_inline(value):
    """Validate inline formatting and links in a heading without active HTML."""
    class InlineOnly(HTMLParser):
        def __init__(self):super().__init__();self.ok=True
        def handle_starttag(self,tag,attrs):
            if tag not in {'a','b','strong','i','em','u','s','span','sub','sup','mark'}:self.ok=False
        def handle_startendtag(self,tag,attrs):self.handle_starttag(tag,attrs)
    try:
        check=InlineOnly();check.feed(value);check.close()
        make_html_block(value)
        return check.ok
    except (ValueError,UnicodeError,RecursionError,TypeError):
        return False


def _normalize_ape_text(value):
    """Strip only APE's presentation wrappers; reject any unrecognized markup."""
    if not isinstance(value, str):
        raise ValueError('invalid_text')

    class Normalizer(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.parts, self.stack, self.changed = [], [], False

        def handle_starttag(self, tag, attrs):
            if tag not in ALLOWED_TAGS | {'span', 'div'}:
                raise ValueError('unsupported_html')
            if len({key for key, _ in attrs}) != len(attrs):
                raise ValueError('duplicate_attribute')
            if 'div' in self.stack and tag in ('div', 'p', 'h1', 'h2', 'h3', 'h4', 'ul', 'ol', 'li', 'blockquote'):
                raise ValueError('nested_block_in_video_wrapper')
            if tag == 'div':
                values = dict(attrs)
                if set(values) - {'class', 'style'} or values.get('class') != 'video_wrapper':
                    raise ValueError('unsupported_div')
                attrs = []
                self.changed = True
            elif tag in ('p', 'span') and all(key == 'style' for key, _ in attrs):
                if attrs or tag == 'span':
                    self.changed = True
                attrs = []
            elif tag == 'a' and all(key in ('href', 'title', 'style', 'target') for key, _ in attrs):
                target = dict(attrs).get('target')
                if target is not None and target not in ('_blank', '_self'):
                    raise ValueError('unsupported_target')
                if any(key in ('style', 'target') for key, _ in attrs):
                    self.changed = True
                    attrs = [(key, val) for key, val in attrs if key not in ('style', 'target')]
                cleaned = []
                for key, val in attrs:
                    if key == 'href' and isinstance(val, str):
                        trimmed = val.strip(' \t\r\n')
                        if trimmed != val:
                            self.changed = True
                        val = trimmed
                    cleaned.append((key, val))
                attrs = cleaned
            elif attrs and not (tag == 'a' and all(key in ('href', 'title') for key, _ in attrs)):
                raise ValueError('unsupported_attribute')
            if tag != 'br':
                self.stack.append(tag)
            if tag != 'span':
                attributes = ''.join(' ' + key + '="' + escape(val or '', quote=True) + '"' for key, val in attrs)
                self.parts.append('<' + ('p' if tag == 'div' else tag) + attributes + '>')

        def handle_startendtag(self, tag, attrs):
            self.handle_starttag(tag, attrs)
            if tag != 'br':
                self.handle_endtag(tag)

        def handle_endtag(self, tag):
            if tag == 'br':
                return
            if not self.stack or self.stack.pop() != tag:
                raise ValueError('unbalanced_html')
            if tag != 'span':
                self.parts.append('</' + ('p' if tag == 'div' else tag) + '>')

        def handle_data(self, data): self.parts.append(data)
        def handle_entityref(self, name): self.parts.append('&' + name + ';')
        def handle_charref(self, name): self.parts.append('&#' + name + ';')
        def handle_comment(self, data): raise ValueError('unsupported_html')
        def handle_decl(self, decl): raise ValueError('unsupported_html')
        def handle_pi(self, data): raise ValueError('unsupported_html')
        def unknown_decl(self, data): raise ValueError('unsupported_html')

    parser = Normalizer()
    parser.feed(value)
    parser.close()
    result = ''.join(parser.parts)
    if parser.stack or not _safe_html(result):
        raise ValueError('unsupported_html')
    return result, parser.changed


def _legacy_player_pairs(root):
    """Recognize explicit AVO main/alternative player labels, never infer by proximity alone."""
    class Label(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.parts = []
            self.valid = True
        def handle_starttag(self, tag, attrs):
            if tag not in ('p', 'strong', 'b', 'em', 'i', 'br') or attrs:
                self.valid = False
            if tag == 'br': self.parts.append(' ')
        def handle_data(self, data): self.parts.append(data)

    def label(node):
        if not isinstance(node, dict) or node.get('name') != 'text' or node.get('children'):
            return None
        fields = node.get('fields')
        if not isinstance(fields, dict) or fields.get('anchor'):
            return None
        if any(v not in (None, '', False, [], {}) for k, v in fields.items() if k not in ('html', 'anchor')):
            return None
        try:
            value, _ = _normalize_ape_text(fields.get('html'))
            p = Label(); p.feed(value); p.close()
            if p.valid:
                text = ' '.join(''.join(p.parts).split()).casefold()
                if 'основной плеер' in text or 'альтернативный плеер' in text:
                    return text
        except (ValueError, RecursionError):
            pass
        return None

    def is_single_video(node):
        if not isinstance(node, dict) or node.get('name') != 'video' or node.get('children'):
            return False
        fields = node.get('fields')
        return (isinstance(fields, dict) and fields.get('videoProvider') in ('youtube', 'rutube')
                and fields.get('videoProvider2') in (None, '', 'youtube', 'rutube') and fields.get('videoSrc2') in (None, '')
                and _player_url(fields.get('videoSrc'), fields.get('videoProvider')))

    pending, sequence = [(root, None)], []
    while pending:
        node, section = pending.pop()
        if isinstance(node, dict) and node.get('name') in ('page', 'section', 'column', 'container'):
            if node.get('name') == 'section':
                section = id(node)
            children = node.get('children', [])
            if isinstance(children, list): pending.extend((child, section) for child in reversed(children))
        else:
            sequence.append((node, section))
    first, skip, labels = {}, set(), set()
    for n, _ in sequence:
        if label(n): labels.add(id(n))
    index = 0
    while index + 3 < len(sequence):
        entries = sequence[index:index + 4]
        (a, sa), (v1, sv1), (b, sb), (v2, sv2) = entries
        if (sa == sv1 == sb == sv2 and label(a) == 'основной плеер' and label(b) == 'альтернативный плеер'
                and is_single_video(v1) and is_single_video(v2)
                and v1['fields']['videoProvider'] != v2['fields']['videoProvider']):
            first[id(v1)] = v2['fields']
            skip.update((id(a), id(b), id(v2)))
            labels.difference_update((id(a), id(b)))
            index += 4
        else:
            index += 1
    return first, skip, labels


def plan_import(payload, image_urls=None):
    """Return a non-mutating import plan; any issue means stop and review.

    Preview format: {format:'preview', account, course_id, lesson_id,
    course_title, lesson_title, content:[{type:'video_pair'|'text'|'links'|
    'audio'|'image', ...}]}.
    APE format: same metadata, format:'ape', ape:{name:'page',children:[...]}.
    A screenshot is {type:'image',image_key:'key',caption:'...'} and must have
    an already-created private URL supplied separately in image_urls.
    IDs are canonical decimal strings. Diagnostic codes never contain URLs or
    source text. All source snapshots remain the caller's responsibility.
    """
    if not isinstance(payload, dict):
        raise ValueError("invalid_payload")
    _bounded(payload)
    image_urls = {} if image_urls is None else image_urls
    if not isinstance(image_urls, dict):
        raise ValueError("invalid_images")
    _bounded(image_urls)
    account = payload.get("account")
    if not isinstance(account, str) or not ACCOUNT.fullmatch(account):
        raise ValueError("invalid_account")
    course, lesson = _id(payload.get("course_id")), _id(payload.get("lesson_id"))
    course_title, lesson_title = payload.get("course_title"), payload.get("lesson_title")
    if any(not isinstance(x, str) or not x.strip() or len(x) > 512 for x in (course_title, lesson_title)):
        raise ValueError("invalid_title")
    plan = {"account": account, "course_id": course, "lesson_id": lesson,
            "course_title": course_title, "lesson_title": lesson_title,
            "blocks": [], "issues": [], "warnings": [], "ready": False}
    blocks, issues = plan["blocks"], plan["issues"]

    def issue(code):
        if code not in issues:
            issues.append(code)

    def paragraph(text):
        if not _safe_html(text):
            issue("unsafe_or_unrecognized_html")
            return
        blocks.append({"type": "paragraph", "data": {"text": text}})

    def video_pair(players):
        if not isinstance(players, list) or len(players) != 2 or not all(isinstance(x, dict) for x in players):
            issue("video_pair_incomplete")
            return
        found = {}
        for player in players:
            if any(v not in (None, "", False, [], {}) for k, v in player.items()
                   if k not in ("provider", "url", "label")):
                issue("unknown_video_fields")
                return
            provider, value = player.get("provider"), player.get("url")
            if provider not in ("youtube", "rutube") or provider in found:
                issue("video_pair_unsupported")
                return
            if not _player_url(value, provider):
                issue("video_url_invalid")
                return
            parsed = urlsplit(value)
            ignored = set(parse_qs(parsed.query, keep_blank_values=True)) - ({"v"} if provider == "youtube" else {"p"})
            if (ignored or parsed.fragment) and "video_player_may_drop_parameters" not in plan["warnings"]:
                plan["warnings"].append("video_player_may_drop_parameters")
            found[provider] = value
        if set(found) != {"youtube", "rutube"}:
            issue("video_pair_incomplete")
            return
        blocks.append({"type": "videoChoice", "data": {**found, "defaultProvider": players[0]["provider"]}})

    def single_video(provider, value):
        if provider not in ('youtube', 'rutube') or not _player_url(value, provider):
            issue('video_url_invalid')
            return
        parsed = urlsplit(value)
        ignored = set(parse_qs(parsed.query, keep_blank_values=True)) - ({'v'} if provider == 'youtube' else {'p'})
        if (ignored or parsed.fragment) and 'video_player_may_drop_parameters' not in plan['warnings']:
            plan['warnings'].append('video_player_may_drop_parameters')
        data = {'youtube': '', 'rutube': '', 'defaultProvider': provider}
        data[provider] = value
        blocks.append({'type': 'videoChoice', 'data': data})

    def entry(item):
        if not isinstance(item, dict):
            issue("invalid_block")
            return
        kind = item.get("type")
        if not isinstance(kind, str):
            issue("invalid_block")
            return
        known_fields = {
            "video_pair": {"type", "order", "players"},
            "text": {"type", "order", "text", "html"},
            "links": {"type", "order", "items"},
            "audio": {"type", "order", "label", "url"},
            "image": {"type", "order", "image_key", "caption"},
        }
        if kind in known_fields and any(v not in (None, "", False, [], {}) for k, v in item.items() if k not in known_fields[kind]):
            issue("unknown_preview_fields")
        if kind == "video_pair":
            video_pair(item.get("players"))
        elif kind == "text":
            if "html" in item:
                paragraph(item["html"])
            elif isinstance(item.get("text"), str):
                paragraph(escape(item["text"]).replace("\n", "<br>"))
            else:
                issue("invalid_text")
        elif kind in ("links", "audio"):
            values = item.get("items") if kind == "links" else [item]
            if not isinstance(values, list):
                issue("invalid_links")
                return
            for link in values:
                if not isinstance(link, dict) or not _url(link.get("url")) or not isinstance(link.get("label"), str):
                    issue("invalid_link")
                    continue
                if kind == "links" and any(v not in (None, "", False, [], {}) for k, v in link.items() if k not in ("label", "url", "file_type_verified")):
                    issue("unknown_link_fields")
                paragraph('<a href="' + escape(link["url"], quote=True) + '">' + escape(link["label"]) + "</a>")
        elif kind == "image":
            key, caption = item.get("image_key"), item.get("caption", "")
            if not isinstance(key, str) or not IMAGE_KEY.fullmatch(key) or not isinstance(caption, str):
                issue("invalid_image")
                return
            url = image_urls.get(key)
            if not isinstance(url, str) or not PRIVATE_FILE.fullmatch(url) or ".." in url:
                issue("image_not_prepared")
                return
            blocks.append({"type": "image", "data": {"url": url, "caption": escape(caption),
                           "withBorder": False, "withBackground": False, "stretched": False}})
        else:
            issue("unknown_block")

    fmt = payload.get("format")
    if fmt == "preview":
        content = payload.get("content")
        if not isinstance(content, list):
            raise ValueError("invalid_content")
        if len(content) > MAX_BLOCKS:
            raise ValueError("too_many_blocks")
        order = [item.get("order") for item in content if isinstance(item, dict) and "order" in item]
        if order and (len(order) != len(content) or any(type(x) is not int or x < 1 for x in order)
                      or order != sorted(set(order))):
            issue("ambiguous_block_order")
        for item in content:
            entry(item)
    elif fmt == "ape":
        root = payload.get("ape")
        if not isinstance(root, dict) or root.get("name") != "page":
            raise ValueError("invalid_ape_root")
        selection = reviewed_selection(root,account,course,lesson)
        omit_rule = CONFIRMED_OMIT_EMPTY_BUTTONS.get((account,course,lesson))
        root_digest = _sha256_text(json.dumps(root,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False)) if omit_rule else None
        if omit_rule and root_digest != omit_rule:
            issue('reviewed_source_changed')
        if (account,course,lesson) in REVIEWED_SELECTIONS and selection is None:
            issue('reviewed_source_changed')
        if selection and selection[0] in ('placeholder','welcome'):
            paragraph('<p>Урок в разработке.</p>' if selection[0] == 'placeholder' else '<p>Добро пожаловать на курс!</p>')
            plan['warnings'].append('user_requested_replacement')
            root = {'name':'page','children':[]}
        legacy_first, legacy_skip, legacy_unmatched = _legacy_player_pairs(root)
        if legacy_unmatched:
            issue('legacy_player_pair_unresolved')
        if legacy_first:
            plan['warnings'].append('legacy_player_labels_combined')
        stack, count, reviewed_section_nodes, selected_buttons = [root], 0, set(), 0
        while stack:
            node = stack.pop()
            count += 1
            if count > MAX_BLOCKS:
                raise ValueError("too_many_blocks")
            if not isinstance(node, dict) or not isinstance(node.get("name"), str):
                issue("invalid_block")
                continue
            if omit_placeholder_section(node,account,course,lesson) or omit_placeholder_node(node,account,course,lesson):
                if 'owner_omitted_placeholder_greeting' not in plan['warnings']:plan['warnings'].append('owner_omitted_placeholder_greeting')
                continue
            kind, fields = node["name"], node.get("fields", {})
            # Decorative separators contain no lesson material. Ignore them
            # before validating their settings, while preserving the raw AVO snapshot.
            if kind == 'spacer':
                if 'user_omitted_separators' not in plan['warnings']: plan['warnings'].append('user_omitted_separators')
                children = node.get('children', [])
                if isinstance(children,list): stack.extend(reversed(children))
                else: issue('invalid_children')
                continue
            if selection and selection[0] == 'videos':
                if kind == 'button':
                    selected_buttons += 1
                    if selected_buttons > selection[1]: continue
                elif kind not in ('page','section','container','column','video'):
                    continue
            if not isinstance(fields, dict):
                issue("invalid_fields")
                continue
            if kind in ('page', 'section', 'container', 'column') and isinstance(node.get('children'), list):
                children = node['children']
                columns = [child for child in children if isinstance(child, dict) and child.get('name') == 'column']
                if len(columns) > 1:
                    # Explicit two-player alternatives are intentionally combined;
                    # ordinary columns must not be silently flattened into a ready lesson.
                    pair_children = [column.get('children') for column in columns]
                    combined_pair = (len(columns) == len(children) == 2
                        and all(isinstance(items, list) and len(items) == 2 for items in pair_children)
                        and id(pair_children[0][0]) in legacy_skip and id(pair_children[0][1]) in legacy_first
                        and id(pair_children[1][0]) in legacy_skip and id(pair_children[1][1]) in legacy_skip)
                    expected_section = CONFIRMED_SINGLE_COLUMN_SECTIONS.get((account,course,lesson))
                    section_hash = _sha256_text(json.dumps(node,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False)) if expected_section else None
                    reviewed_section = expected_section is not None and section_hash == expected_section
                    if reviewed_section:
                        reviewed_section_nodes.update([id(node)]+[id(column) for column in columns])
                    if not combined_pair and (reviewed_section or (account,course,lesson) in CONFIRMED_SINGLE_COLUMN_LESSONS):
                        if 'user_requested_single_column' not in plan['warnings']:
                            plan['warnings'].append('user_requested_single_column')
                    elif not combined_pair:
                        if 'user_requested_single_column' not in plan['warnings']:
                            plan['warnings'].append('user_requested_single_column')
            if node.get("style") and kind != 'spacer':
                if "ape_layout_settings_not_rendered" not in plan["warnings"]:
                    plan["warnings"].append("ape_layout_settings_not_rendered")
            extra_node_keys = set(node) - {"id", "name", "fields", "children", "style"}
            if any(node[k] not in (None, "", False, [], {}) for k in extra_node_keys):
                issue("unknown_node_fields")
            if kind == "video":
                allowed = {"anchor", "videoProvider", "videoSrc", "nativePlayer", "posterSrc",
                           "isShowProgressControl", "isShowFastRewindButtons", "videoProvider2",
                           "videoSrc2", "nativePlayer2", "posterSrc2", "isShowProgressControl2",
                           "isShowFastRewindButtons2", "embeddedHtml", "html", "isFloating"}
                if any(v not in (None, "", False, [], {}) for k, v in fields.items() if k not in allowed):
                    issue("unknown_video_fields")
                if any(fields.get(k) not in (None, "", False) for k in ("anchor", "posterSrc", "posterSrc2", "embeddedHtml")):
                    issue("unsupported_video_settings")
                if fields.get("html") not in (None, "", "Видео"):
                    issue("unsupported_video_settings")
                if any(k in fields for k in ("nativePlayer", "nativePlayer2", "isShowProgressControl", "isShowFastRewindButtons", "isFloating")):
                    if "ape_video_settings_not_reconstructed" not in plan["warnings"]:
                        plan["warnings"].append("ape_video_settings_not_reconstructed")
                if id(node) in legacy_first:
                    other = legacy_first[id(node)]
                    video_pair([{'provider': fields.get('videoProvider'), 'url': fields.get('videoSrc')},
                                {'provider': other.get('videoProvider'), 'url': other.get('videoSrc')}])
                elif id(node) in legacy_skip:
                    pass
                elif (fields.get('videoProvider') == 'youtube' and fields.get('videoProvider2') in (None, '', 'youtube', 'rutube')
                      and fields.get('videoSrc2') in (None, '') and isinstance(fields.get('videoSrc'),str)
                      and CONFIRMED_CONCATENATED_YOUTUBE.get((account,course,lesson)) == _sha256_text(fields['videoSrc'])
                      and re.fullmatch(r'https://youtu\.be/[A-Za-z0-9_-]{11}https://youtu\.be/[A-Za-z0-9_-]{11}',fields['videoSrc'])):
                    second = fields['videoSrc'][len('https://youtu.be/') + 11:]
                    single_video('youtube',second)
                    if 'user_selected_second_youtube' not in plan['warnings']:
                        plan['warnings'].append('user_selected_second_youtube')
                elif (fields.get('videoProvider') in ('youtube','rutube')
                      and fields.get('videoProvider2') == fields.get('videoProvider')
                      and isinstance(fields.get('videoSrc'),str) and fields.get('videoSrc')
                      and fields.get('videoSrc2') == fields.get('videoSrc')):
                    single_video(fields['videoProvider'],fields['videoSrc'])
                    if 'duplicate_video_sources_combined' not in plan['warnings']:
                        plan['warnings'].append('duplicate_video_sources_combined')
                elif fields.get('videoProvider2') in (None, '', 'youtube', 'rutube') and fields.get('videoSrc2') in (None, ''):
                    single_video(fields.get('videoProvider'), fields.get('videoSrc'))
                else:
                    video_pair([{"provider": fields.get("videoProvider"), "url": fields.get("videoSrc")},
                                {"provider": fields.get("videoProvider2"), "url": fields.get("videoSrc2")}])
            elif kind == 'header':
                allowed = {'anchor', 'html', 'format'}
                markup = fields.get('html')
                source_format = fields.get('format')
                if (CONFIRMED_OMIT_HEADERS.get((account,course,lesson)) == _sha256_text(markup)
                        and (account,course,lesson) in CONFIRMED_OMIT_HEADERS
                        and not node.get('children') and not fields.get('anchor')
                        and not any(v not in (None,'',False,[],{}) for k,v in fields.items() if k not in allowed)):
                    if 'owner_omitted_trainer_link' not in plan['warnings']:plan['warnings'].append('owner_omitted_trainer_link')
                    continue
                match = re.fullmatch(r'\s*<h([1-6])>(.*?)</h\1>\s*', markup, re.I | re.S) if isinstance(markup, str) else None
                if (fields.get('anchor') or any(v not in (None, '', False, [], {}) for k, v in fields.items() if k not in allowed)
                        or source_format not in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6') or not match
                        or not _safe_heading_inline(match.group(2))
                        or re.search(r'<\s*(?:br|p|h[1-6]|ul|ol|li|blockquote)\b', match.group(2), re.I)):
                    issue('unsupported_header')
                else:
                    level = int(match.group(1))
                    blocks.append({'type': 'header', 'data': {'text': match.group(2), 'level': level}})
                    if source_format != 'h' + str(level) and 'ape_heading_format_mismatch' not in plan['warnings']:
                        plan['warnings'].append('ape_heading_format_mismatch')
            elif kind == "text":
                if fields.get("anchor") or any(v not in (None, "", False, [], {}) for k, v in fields.items() if k not in ("html", "anchor")):
                    issue("unsupported_text_settings")
                if (CONFIRMED_HTML_FIELDS.get((account,course,lesson)) == _sha256_text(fields.get('html'))
                        and (account,course,lesson) in CONFIRMED_HTML_FIELDS and node.get('children',[])==[]):
                    try:
                        block=make_html_block(fields.get('html'))
                    except (ValueError,UnicodeError,RecursionError):
                        issue('unsafe_or_unrecognized_html')
                    else:
                        if id(node) not in legacy_skip:
                            blocks.append(block)
                            if 'ape_static_html_frame_unverified' not in plan['warnings']:plan['warnings'].append('ape_static_html_frame_unverified')
                    continue
                try:
                    normalized, changed = _normalize_ape_text(fields.get('html'))
                    if changed and 'ape_text_formatting_not_reconstructed' not in plan['warnings']:
                        plan['warnings'].append('ape_text_formatting_not_reconstructed')
                    if id(node) not in legacy_skip:
                        paragraph(normalized)
                except (ValueError, RecursionError):
                    try:
                        block = make_html_block(fields.get('html'))
                    except (ValueError, UnicodeError, RecursionError):
                        source = fields.get('html')
                        audio_hash = CONFIRMED_DRIVE_AUDIO_LINKS.get((account,course,lesson))
                        if audio_hash is not None and audio_hash == _sha256_text(source):
                            try:
                                audio_blocks=split_reviewed_audio_links(source)
                            except (ValueError, UnicodeError, RecursionError):
                                issue('unsafe_or_unrecognized_html')
                            else:
                                if id(node) not in legacy_skip:
                                    blocks.extend(audio_blocks)
                                    for warning in ('ape_static_html_frame_unverified','user_requested_audio_link'):
                                        if warning not in plan['warnings']:plan['warnings'].append(warning)
                        else:
                            expected_hash = CONFIRMED_TEXT_ONLY_ANSWER_FORMS.get((account,course,lesson))
                            confirmed = expected_hash is not None and expected_hash == _sha256_text(source)
                            if confirmed:
                                try:
                                    block = make_html_block(strip_empty_answer_form(source))
                                except (ValueError, UnicodeError, RecursionError):
                                    issue('unsafe_or_unrecognized_html')
                                else:
                                    if id(node) not in legacy_skip:
                                        blocks.append(block)
                                        for warning in ('ape_static_html_frame_unverified','answer_form_omitted_at_user_request'):
                                            if warning not in plan['warnings']:plan['warnings'].append(warning)
                            else:
                                issue('unsafe_or_unrecognized_html')
                    else:
                        if id(node) not in legacy_skip:
                            blocks.append(block)
                            if 'ape_static_html_frame_unverified' not in plan['warnings']:
                                plan['warnings'].append('ape_static_html_frame_unverified')
            elif kind == 'button':
                if (omit_rule and root_digest == omit_rule and not node.get('children')
                        and fields.get('html') == 'АУДИОЗАПИСЬ 2' and fields.get('url') == ''):
                    if 'user_omitted_empty_button' not in plan['warnings']:
                        plan['warnings'].append('user_omitted_empty_button')
                    continue
                allowed = {'anchor', 'html', 'icon', 'linkType', 'url', 'blank', 'toAnchor', 'event'}
                button_url = fields.get('url')
                if isinstance(button_url,str): button_url = button_url.strip()
                label = fields.get('html')
                if isinstance(label,str): label = re.sub(r'<br\s*/?>', ' ', label, flags=re.I).strip()
                if (fields.get('linkType') != 'url' or any(fields.get(k) not in (None, '', False) for k in ('anchor','icon','toAnchor','event'))
                        or any(v not in (None, '', False, [], {}) for k, v in fields.items() if k not in allowed)
                        or not isinstance(label, str) or '<' in label or '>' in label
                        or not _url(button_url)):
                    issue('unsupported_button')
                else:
                    if selection and selection[0] == 'videos':
                        blocks.append({'type':'lessonButton','data':{'text':label,'url':button_url,
                            'size':'medium','background':'#2563eb','color':'#ffffff','newTab':bool(fields.get('blank'))}})
                    else:
                        paragraph('<a href="' + escape(button_url, quote=True) + '">' + escape(label) + '</a>')
                        if fields.get('blank') and 'ape_button_new_tab_not_reconstructed' not in plan['warnings']:
                            plan['warnings'].append('ape_button_new_tab_not_reconstructed')
            elif kind == 'image':
                allowed = {'anchor', 'imageSrc'}
                if (fields.get('anchor') or not _url(fields.get('imageSrc'))
                        or any(v not in (None, '', False, [], {}) for k, v in fields.items() if k not in allowed)):
                    issue('unsupported_image_settings')
                else:
                    entry({'type': 'image', 'image_key': node.get('id'), 'caption': ''})
            elif kind == "page":
                known = {"commonFontName", "commonFontLink", "commonFontFamily", "headingFontName", "headingFontLink", "headingFontFamily", "fontPair", "backgroundOverlayColor"}
                if any(v not in (None, "", False, [], {}) for k, v in fields.items() if k not in known):
                    issue("unknown_page_fields")
                overlay = fields.get('backgroundOverlayColor')
                if overlay not in (None, '', False, {}):
                    if (not isinstance(overlay,dict) or set(overlay) != {'enabled','r','g','b','a'}
                            or overlay.get('enabled') is not False
                            or any(type(overlay.get(k)) is not int or not 0 <= overlay[k] <= 255 for k in ('r','g','b'))
                            or type(overlay.get('a')) not in (int,float) or not math.isfinite(overlay['a']) or not 0 <= overlay['a'] <= 1):
                        issue('unsupported_background_overlay')
                if fields and "ape_layout_settings_not_rendered" not in plan["warnings"]:
                    plan["warnings"].append("ape_layout_settings_not_rendered")
            elif kind in ("section", "column", "container"):
                if fields.get('backgroundOverlayColor') and 'ape_layout_settings_not_rendered' not in plan['warnings']:
                    plan['warnings'].append('ape_layout_settings_not_rendered')
                if not (selection and selection[0] == 'videos') and id(node) not in reviewed_section_nodes and any(v not in (None, "", False, [], {}) for k,v in fields.items() if k != 'backgroundOverlayColor'):
                    issue("unsupported_container_fields")
            else:
                issue("unknown_block")
            children = node.get("children", [])
            if not isinstance(children, list):
                issue("invalid_children")
            else:
                stack.extend(reversed(children))
    else:
        raise ValueError("unknown_format")
    if not blocks:
        issue("empty_lesson")
    plan["ready"] = not issues
    return plan
