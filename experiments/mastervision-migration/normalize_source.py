"""Recognize standalone video iframes locally, retaining the exact original APE.

This changes no shared converter and never executes source HTML. Mixed text,
unknown markup and unrecognized players remain explicit review cases.
"""
import copy
from functools import lru_cache
from html import escape
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlsplit

from importer import ACCOUNT, ORIGIN, Review
from normalize_editor_nodes import normalize_nodes
from normalize_inline_images import normalize_inline_images, CODE as IMAGE_CODE


CODE = "embedded_video_iframe_normalized"
TABLE_CODE = "static_table_presentation_normalized"
FEATURES = {"accelerometer", "autoplay", "clipboard-write", "encrypted-media", "gyroscope",
            "picture-in-picture", "web-share", "fullscreen"}


@lru_cache(maxsize=1)
def static_validator():
    # Reuse the pure existing validator without requiring a Frappe installation
    # or a particular working directory. Accepted HTML stays byte-for-byte intact.
    path = Path(__file__).resolve().parents[2] / "lms/lms/avo_html_fragment.py"
    spec = importlib.util.spec_from_file_location("mastervision_static_html", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.make_html_block


def player(source):
    if not isinstance(source, str) or re.search(r"[\x00-\x20\x7f\\]", source):
        raise Review("embedded_iframe_requires_review")
    try:
        url = urlsplit(source)
        if url.scheme != "https" or url.username or url.password or url.port is not None or url.fragment:
            raise ValueError()
        pairs = parse_qsl(url.query, keep_blank_values=True, strict_parsing=True)
        query = dict(pairs)
        if len(pairs) != len(query):
            raise ValueError()
        if url.hostname in {"vimeo.com", "www.vimeo.com", "player.vimeo.com"}:
            raise Review("vimeo_video_unavailable")
        if url.hostname in {"youtube.com", "www.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com"}:
            if not re.fullmatch(r"/embed/[A-Za-z0-9_-]{11}/?", url.path):
                raise ValueError()
            for key, value in query.items():
                if key in {"start", "end"}:
                    if not re.fullmatch(r"[0-9]{1,7}", value):
                        raise ValueError()
                elif key not in {"rel", "autoplay", "controls", "showinfo", "modestbranding", "playsinline"} or value not in {"0", "1"}:
                    raise ValueError()
            return "youtube", source
        if url.hostname in {"rutube.ru", "www.rutube.ru"}:
            if not re.fullmatch(r"/play/embed/[0-9a-fA-F]{32}/?", url.path) or set(query) - {"p"}:
                raise ValueError()
            if "p" in query and not re.fullmatch(r"[A-Za-z0-9_-]{1,300}", query["p"]):
                raise ValueError()
            return "rutube", source
    except (ValueError, UnicodeError):
        pass
    raise Review("embedded_iframe_requires_review")


class SingleFrame(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.video = [], None

    def handle_starttag(self, tag, attrs):
        if len({key for key, _ in attrs}) != len(attrs) or len(self.stack) > 20:
            raise Review("embedded_iframe_requires_review")
        if tag == "iframe":
            if self.video or "iframe" in self.stack:
                raise Review("embedded_iframe_requires_review")
            values = dict(attrs)
            if set(values) - {"src", "width", "height", "frameborder", "allow", "allowfullscreen", "webkitallowfullscreen", "mozallowfullscreen"}:
                raise Review("embedded_iframe_requires_review")
            for key in ("width", "height"):
                if key in values and (not isinstance(values[key], str) or not re.fullmatch(r"[1-9][0-9]{0,3}", values[key])):
                    raise Review("embedded_iframe_requires_review")
            if "frameborder" in values and values["frameborder"] not in {"0", "1"}:
                raise Review("embedded_iframe_requires_review")
            for boolean in ('allowfullscreen', 'webkitallowfullscreen', 'mozallowfullscreen'):
                if boolean in values and values[boolean] not in {None, '', 'true', boolean}:
                    raise Review("embedded_iframe_requires_review")
            if "allow" in values and (not isinstance(values["allow"], str) or not {part.strip() for part in values["allow"].split(";") if part.strip()} <= FEATURES):
                raise Review("embedded_iframe_requires_review")
            self.video = player(values.get("src"))
        elif tag not in {"p", "div", "span", "br"} or attrs or "iframe" in self.stack:
            raise Review("embedded_iframe_requires_review")
        if tag != "br":
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag != "br":
            raise Review("embedded_iframe_requires_review")
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "br":
            return
        if not self.stack or self.stack.pop() != tag:
            raise Review("embedded_iframe_requires_review")

    def handle_data(self, data):
        if data.strip():
            raise Review("embedded_iframe_requires_review")

    def handle_comment(self, data):
        raise Review("embedded_iframe_requires_review")

    handle_decl = handle_comment
    handle_pi = handle_comment
    unknown_decl = handle_comment


def presentation_css(value):
    if not isinstance(value, str) or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\\@]", value):
        raise Review("static_table_requires_review")
    plain = re.sub(r"/\*.*?\*/", "", value, flags=re.S)
    if re.search(r"(?:^|[;{])\s*(?:content|quotes|counter-reset|counter-increment|behavior|-moz-binding)\s*:", plain, re.I):
        raise Review("static_table_requires_review")
    if any(name.lower() not in {"rgb", "rgba", "hsl", "hsla", "calc", "min", "max", "clamp"}
           for name in re.findall(r"([A-Za-z_-][A-Za-z0-9_-]*)\s*\(", plain)):
        raise Review("static_table_requires_review")


class TablePresentation(HTMLParser):
    """Regenerate static markup, removing only approved presentation metadata."""
    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.markup, self.parts, self.stack = markup, [], []
        self.starts = [0] + [i + 1 for i, char in enumerate(markup) if char == '\n']
        self.stylesheet, self.iframe = None, None
        self.stats = {"style_blocks": 0, "style_attributes": 0, "presentation_attributes": 0, "header_cells": 0, "header_groups": 0}
        self.allowed = static_validator().__globals__["TAGS"] | {"thead", "th"}
        self.void = {"br", "hr", "col"}

    def position(self):
        line, column = self.getpos()
        return self.starts[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if tag not in self.allowed or len({k for k, _ in attrs}) != len(attrs) or any(k.startswith('on') for k, _ in attrs) or len(self.stack) > 100:
            raise Review("static_table_requires_review")
        if self.iframe is not None:
            if tag == 'iframe':
                raise Review("static_table_requires_review")
            if tag not in self.void:
                self.stack.append(tag)
            return
        if tag == 'iframe':
            self.iframe = self.position()
            self.stack.append(tag)
            return
        if tag == 'style':
            if dict(attrs) not in ({}, {"type": "text/css"}):
                raise Review("static_table_requires_review")
            self.stylesheet = []
            self.stats['style_blocks'] += 1
            self.stack.append(tag)
            return
        kept = []
        for key, value in attrs:
            remove = False
            if key == 'style':
                presentation_css(value)
                self.stats['style_attributes'] += 1
                remove = True
            elif tag == 'table' and key in {'cellspacing', 'cellpadding', 'border'}:
                if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,4}', value):
                    raise Review("static_table_requires_review")
                remove = True
            elif tag == 'table' and key == 'xmlns':
                if value not in {'http://www.w3.org/1999/xhtml', 'https://www.w3.org/1999/xhtml'}:
                    raise Review("static_table_requires_review")
                remove = True
            elif tag == 'td' and key in {'data-sheets-value', 'data-sheets-numberformat'}:
                if not isinstance(value, str):
                    raise Review("static_table_requires_review")
                remove = True
            elif tag in {'table', 'tr', 'td', 'th', 'col', 'colgroup'} and key in {'width', 'height'}:
                if not isinstance(value, str) or not re.fullmatch(r'(?:[0-9]{1,5}(?:px|pt|em|rem|%)?|auto)', value):
                    raise Review("static_table_requires_review")
                remove = True
            if remove:
                if key != 'style':
                    self.stats['presentation_attributes'] += 1
            else:
                kept.append(' ' + key + ('' if value is None else '="' + escape(value, quote=True) + '"'))
        mapped = {'thead': 'tbody', 'th': 'td'}.get(tag, tag)
        self.parts.append('<' + mapped + ''.join(kept) + '>')
        if tag == 'thead':
            self.stats['header_groups'] += 1
        if tag == 'th':
            self.stats['header_cells'] += 1
            self.parts.append('<strong>')
        if tag not in self.void:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.void:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in self.void:
            return
        if not self.stack or self.stack.pop() != tag:
            raise Review("static_table_requires_review")
        if self.iframe is not None:
            if tag == 'iframe':
                closing = re.match(r'</\s*iframe\s*>', self.markup[self.position():], re.I)
                if not closing:
                    raise Review("static_table_requires_review")
                fragment = self.markup[self.iframe:self.position() + len(closing.group())]
                try:
                    static_validator()(fragment)
                except (ValueError, UnicodeError, RecursionError):
                    raise Review("static_table_requires_review") from None
                self.parts.append(fragment)
                self.iframe = None
            return
        if tag == 'style':
            presentation_css(''.join(self.stylesheet))
            self.stylesheet = None
            return
        self.parts.append('</strong></td>' if tag == 'th' else '</' + {'thead': 'tbody'}.get(tag, tag) + '>')

    def handle_data(self, data):
        if self.iframe is not None:
            return
        if self.stylesheet is not None:
            self.stylesheet.append(data)
        else:
            self.parts.append(escape(data, quote=False))

    def handle_comment(self, data):
        raise Review("static_table_requires_review")

    handle_decl = handle_comment
    handle_pi = handle_comment
    unknown_decl = handle_comment


def table_content(markup):
    class Content(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.style, self.text, self.hrefs, self.cells, self.active, self.order = False, [], [], [], [], []
        def handle_starttag(self, tag, attrs):
            if tag == 'style': self.style = True
            if tag == 'tr': self.order.append('row')
            if tag in {'td', 'th'}:
                self.order.append('cell'); self.cells.append([]); self.active.append(len(self.cells) - 1)
            self.hrefs.extend(value for key, value in attrs if key == 'href')
        def handle_endtag(self, tag):
            if tag == 'style': self.style = False
            if tag in {'td', 'th'} and self.active: self.active.pop()
        def handle_data(self, data):
            if not self.style:
                self.text.append(data)
                for index in self.active: self.cells[index].append(data)
    parser = Content(); parser.feed(markup); parser.close()
    return ''.join(parser.text), parser.hrefs, [''.join(v) for v in parser.cells], parser.order


def clean_table(markup):
    if len(markup.encode('utf-8')) > 200000:
        raise Review("static_table_requires_review")
    parser = TablePresentation(markup); parser.feed(markup); parser.close()
    if parser.stack or parser.iframe is not None or parser.stylesheet is not None or not any(parser.stats.values()):
        raise Review("static_table_requires_review")
    cleaned = ''.join(parser.parts)
    try:
        static_validator()(cleaned)
    except (ValueError, UnicodeError, RecursionError):
        raise Review("static_table_requires_review") from None
    if table_content(markup) != table_content(cleaned):
        raise Review("static_table_content_changed")
    return cleaned, parser.stats


def normalize_payload(payload):
    """Return (private payload copy, diagnostic codes), without changing input.

    Every converted node contains precisely one supported iframe and inert empty
    wrappers. Adjacent videos are never paired here. Existing typed pairs remain
    unchanged. Metadata is added only when at least one node was converted.
    """
    if not isinstance(payload, dict) or (payload.get("account"), payload.get("source_origin")) != (ACCOUNT, ORIGIN):
        raise Review("normalization_account_mismatch")
    try:
        result = json.loads(json.dumps(payload, allow_nan=False))
    except (ValueError, TypeError, RecursionError):
        raise Review("normalization_source_invalid") from None
    reserved = {"source_original_ape", "source_normalization"}
    if reserved & set(result):
        if not reserved <= set(result):
            raise Review("normalization_metadata_conflict")
        original = copy.deepcopy(result)
        original["ape"] = original.pop("source_original_ape")
        original.pop("source_normalization")
        regenerated, codes = normalize_payload(original)
        if not codes or regenerated != result:
            raise Review("normalization_metadata_conflict")
        return regenerated, codes
    ape = result.get("ape")
    if result.get("format") != "ape" or not isinstance(ape, dict) or ape.get("name") != "page":
        raise Review("normalization_source_invalid")
    original_ape, changed, table_changes = copy.deepcopy(ape), [], []
    ape, editor_changes = normalize_nodes(ape, static_validator())
    ape, image_changes = normalize_inline_images(ape, static_validator())
    result['ape'] = ape

    def visit(node, path):
        if len(path) > 100 or not isinstance(node, dict) or not isinstance(node.get("name"), str) or not isinstance(node.get("fields", {}), dict) or not isinstance(node.get("children", []), list):
            raise Review("normalization_source_invalid")
        fields = node.get("fields", {})
        markup = fields.get("html")
        if isinstance(markup, str) and re.search(r'<\s*table\b', markup, re.I):
            try:
                static_validator()(markup)
            except (ValueError, UnicodeError, RecursionError):
                if node['name'] not in {'text', 'code'} or node.get('children'):
                    raise Review("static_table_requires_review")
                cleaned, statistics = clean_table(markup)
                fields['html'], markup = cleaned, cleaned
                table_changes.append({'path': path, **statistics})
        candidate = isinstance(markup, str) and re.search(r"<\s*iframe\b", markup, re.I)
        if candidate:
            try:
                static_validator()(markup)
            except (ValueError, UnicodeError, RecursionError):
                pass
            else:
                candidate = False
        if candidate:
            if node["name"] not in {"text", "code"} or node.get("children") or fields.get("anchor") or any(value not in (None, "", False, [], {}) for key, value in fields.items() if key not in {"html", "anchor"}):
                raise Review("embedded_iframe_requires_review")
            if len(markup.encode("utf-8")) > 200000:
                raise Review("embedded_iframe_requires_review")
            parser = SingleFrame()
            parser.feed(markup)
            parser.close()
            if parser.stack or not parser.video:
                raise Review("embedded_iframe_requires_review")
            provider, source = parser.video
            node["name"], node["fields"] = "video", {"videoProvider": provider, "videoSrc": source}
            changed.append({"path": path, "provider": provider})
        for index, child in enumerate(node.get("children", [])):
            visit(child, path + [index])

    visit(ape, [])
    codes = ([CODE] if changed else []) + ([TABLE_CODE] if table_changes else [])
    codes.extend(dict.fromkeys(change['code'] for change in editor_changes))
    if image_changes:
        codes.append(IMAGE_CODE)
    if codes:
        result["source_original_ape"] = original_ape
        if image_changes:
            result["source_normalization"] = {"version": 3, "kind": "mastervision_editor_normalization", "codes": codes,
                                               "blocks": changed, "table_blocks": table_changes, "editor_blocks": editor_changes,
                                               "inline_image_blocks": image_changes}
        elif table_changes or editor_changes:
            result["source_normalization"] = {"version": 2, "kind": "mastervision_editor_normalization", "codes": codes,
                                               "blocks": changed, "table_blocks": table_changes, "editor_blocks": editor_changes}
        else:
            result["source_normalization"] = {"version": 1, "kind": "mastervision_single_iframe", "codes": [CODE], "blocks": changed}
    return result, codes
