"""Recognize standalone video iframes locally, retaining the exact original APE.

This changes no shared converter and never executes source HTML. Mixed text,
unknown markup and unrecognized players remain explicit review cases.
"""
import copy
from functools import lru_cache
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlsplit

from importer import ACCOUNT, ORIGIN, Review


CODE = "embedded_video_iframe_normalized"
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
            if set(values) - {"src", "width", "height", "frameborder", "allow", "allowfullscreen"}:
                raise Review("embedded_iframe_requires_review")
            for key in ("width", "height"):
                if key in values and (not isinstance(values[key], str) or not re.fullmatch(r"[1-9][0-9]{0,3}", values[key])):
                    raise Review("embedded_iframe_requires_review")
            if "frameborder" in values and values["frameborder"] not in {"0", "1"}:
                raise Review("embedded_iframe_requires_review")
            if "allowfullscreen" in values and values["allowfullscreen"] not in {None, "", "true", "allowfullscreen"}:
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
    original_ape, changed = copy.deepcopy(ape), []

    def visit(node, path):
        if len(path) > 100 or not isinstance(node, dict) or not isinstance(node.get("name"), str) or not isinstance(node.get("fields", {}), dict) or not isinstance(node.get("children", []), list):
            raise Review("normalization_source_invalid")
        fields = node.get("fields", {})
        markup = fields.get("html")
        candidate = isinstance(markup, str) and re.search(r"<\s*iframe\b", markup, re.I)
        if candidate:
            try:
                static_validator()(markup)
            except (ValueError, UnicodeError, RecursionError):
                pass
            else:
                candidate = False
        if candidate:
            if node["name"] != "text" or node.get("children") or fields.get("anchor") or any(value not in (None, "", False, [], {}) for key, value in fields.items() if key not in {"html", "anchor"}):
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
    if changed:
        result["source_original_ape"] = original_ape
        result["source_normalization"] = {"version": 1, "kind": "mastervision_single_iframe", "codes": [CODE], "blocks": changed}
    return result, [CODE] if changed else []
