"""Pure, conservative AVO lesson-to-EditorJS conversion; no I/O or execution."""
from html import escape
from html.parser import HTMLParser
import json
import re
from urllib.parse import parse_qs, urlsplit
from lms.lms.avo_html_fragment import make_html_block

MAX_BYTES = 16 * 1024 * 1024
MAX_DEPTH = 100
MAX_NODES = 150000  # JSON values, not lesson blocks; APE blocks remain capped separately.
MAX_BLOCKS = 1000
ACCOUNT = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
IMAGE_KEY = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")
PRIVATE_FILE = re.compile(r"^/private/files/[a-zA-Z0-9][a-zA-Z0-9_.-]{0,180}$")
ALLOWED_TAGS = {"p", "br", "strong", "b", "em", "i", "u", "s", "a", "ul", "ol", "li",
                "h1", "h2", "h3", "h4", "blockquote", "code"}


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
            if key in seen or tag != "a" or key not in ("href", "title"):
                self.ok = False
            seen.add(key)
            if key == "href" and not _url(value):
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
    if any(not isinstance(x, str) or not x.strip() or len(x) > 500 for x in (course_title, lesson_title)):
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
        legacy_first, legacy_skip, legacy_unmatched = _legacy_player_pairs(root)
        if legacy_unmatched:
            issue('legacy_player_pair_unresolved')
        if legacy_first:
            plan['warnings'].append('legacy_player_labels_combined')
        stack, count = [root], 0
        while stack:
            node = stack.pop()
            count += 1
            if count > MAX_BLOCKS:
                raise ValueError("too_many_blocks")
            if not isinstance(node, dict) or not isinstance(node.get("name"), str):
                issue("invalid_block")
                continue
            kind, fields = node["name"], node.get("fields", {})
            if not isinstance(fields, dict):
                issue("invalid_fields")
                continue
            if node.get("style"):
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
                elif fields.get('videoProvider2') in (None, '', 'youtube', 'rutube') and fields.get('videoSrc2') in (None, ''):
                    single_video(fields.get('videoProvider'), fields.get('videoSrc'))
                else:
                    video_pair([{"provider": fields.get("videoProvider"), "url": fields.get("videoSrc")},
                                {"provider": fields.get("videoProvider2"), "url": fields.get("videoSrc2")}])
            elif kind == 'header':
                allowed = {'anchor', 'html', 'format'}
                markup = fields.get('html')
                source_format = fields.get('format')
                match = re.fullmatch(r'\s*<h([1-4])>(.*?)</h\1>\s*', markup, re.I | re.S) if isinstance(markup, str) else None
                if (fields.get('anchor') or any(v not in (None, '', False, [], {}) for k, v in fields.items() if k not in allowed)
                        or source_format not in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6') or not match
                        or not _safe_html(markup) or not _safe_html(match.group(2))
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
                        issue('unsafe_or_unrecognized_html')
                    else:
                        if id(node) not in legacy_skip:
                            blocks.append(block)
                            if 'ape_static_html_frame_unverified' not in plan['warnings']:
                                plan['warnings'].append('ape_static_html_frame_unverified')
            elif kind == 'button':
                allowed = {'anchor', 'html', 'icon', 'linkType', 'url', 'blank', 'toAnchor', 'event'}
                if (fields.get('linkType') != 'url' or any(fields.get(k) not in (None, '', False) for k in ('anchor','icon','toAnchor','event'))
                        or any(v not in (None, '', False, [], {}) for k, v in fields.items() if k not in allowed)
                        or not isinstance(fields.get('html'), str) or '<' in fields['html'] or '>' in fields['html']
                        or not _url(fields.get('url'))):
                    issue('unsupported_button')
                else:
                    paragraph('<a href="' + escape(fields['url'], quote=True) + '">' + escape(fields['html']) + '</a>')
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
                known = {"commonFontName", "commonFontLink", "commonFontFamily", "headingFontName", "headingFontLink", "headingFontFamily", "fontPair"}
                if any(v not in (None, "", False, [], {}) for k, v in fields.items() if k not in known):
                    issue("unknown_page_fields")
                if fields and "ape_layout_settings_not_rendered" not in plan["warnings"]:
                    plan["warnings"].append("ape_layout_settings_not_rendered")
            elif kind in ("section", "column", "container"):
                if any(v not in (None, "", False, [], {}) for v in fields.values()):
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
