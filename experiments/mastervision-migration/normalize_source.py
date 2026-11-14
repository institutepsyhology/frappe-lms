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
from normalize_button_labels import normalize_button_labels, CODE as BUTTON_CODE
from normalize_accordions import normalize_accordions, CODE as ACCORDION_CODE
from normalize_stage_widgets import normalize_stage_widgets, CODE as STAGE_CODE
from normalize_approved_images import normalize_approved_images, CODE as OMIT_IMAGE_CODE
from normalize_image_labels import normalize_image_labels, CODE as IMAGE_LABEL_CODE
from normalize_static_presentation import normalize_static_presentation, CODE as PRESENTATION_CODE
from normalize_empty_material_buttons import normalize_empty_material_buttons, CODE as EMPTY_BUTTON_CODE
from normalize_video_values import normalize_video_values, CODE as VIDEO_VALUE_CODE
from normalize_empty_discussion_widgets import normalize_empty_discussion_widgets, CODE as EMPTY_WIDGET_CODE
from normalize_keyboard_markup import normalize_keyboard_markup, CODE as KEYBOARD_CODE
from normalize_redundant_link_metadata import normalize_redundant_link_metadata, CODE as LINK_METADATA_CODE
from normalize_legacy_html_decorations import normalize_legacy_html_decorations, CODE as LEGACY_DECORATION_CODE
from normalize_native_video_sources import normalize_native_video_sources, CODE as VIDEO_SOURCE_CODE
from normalize_owner_media_omissions import normalize_owner_media_omissions, CODE as OWNER_MEDIA_CODE
from normalize_owner_material_links import normalize_owner_material_links, CODE as OWNER_MATERIAL_CODE
from normalize_image_wrapper_layout import normalize_image_wrapper_layout, CODE as IMAGE_WRAPPER_CODE
from normalize_annotated_material_buttons import normalize_annotated_material_buttons, CODE as ANNOTATED_MATERIAL_CODE
from normalize_reviewed_static_material import normalize_reviewed_static_material
from normalize_missing_course_images import normalize_missing_course_images
from normalize_reviewed_image_rotation import normalize_reviewed_image_rotation, CODE as REVIEWED_ROTATION_CODE
from normalize_remaining_static_material import normalize_remaining_static_material
from normalize_reviewed_legacy_players import normalize_reviewed_legacy_players
from normalize_audio import normalize_audio, CODE as AUDIO_CODE


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


def normalize_payload(payload, audio_assets=None):
    """Return (private payload copy, diagnostic codes), without changing input.

    Every converted node contains precisely one supported iframe and inert empty
    wrappers. Adjacent videos are never paired here. Existing typed pairs remain
    unchanged. Metadata is added only when at least one node was converted.
    Audio receipts are injected by the caller; only used, validated entries are
    retained. Existing v7 snapshots can reproduce their private links without
    requiring an external mapping on every read.
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
        metadata = result['source_normalization']
        is_audio = isinstance(metadata, dict) and (metadata.get('version') == 7 or
            metadata.get('version') in (8,9,10,11,12,13,14,15,16,17,18,19,20) and ('audio_assets' in metadata or bool(metadata.get('audio_blocks'))))
        stored_assets = metadata.get('audio_assets') if is_audio else None
        if is_audio:
            if (not isinstance(stored_assets, dict) or not stored_assets
                    or any(not isinstance(key, str) or not re.fullmatch('[0-9a-f]{64}', key)
                           for key in stored_assets)):
                raise Review('normalization_metadata_conflict')
            if audio_assets is not None and (not isinstance(audio_assets, dict)
                    or any(key not in audio_assets or audio_assets[key] != receipt
                           for key, receipt in stored_assets.items())):
                raise Review('normalization_metadata_conflict')
        original = copy.deepcopy(result)
        original["ape"] = original.pop("source_original_ape")
        original.pop("source_normalization")
        if is_audio:
            try:
                regenerated, codes = normalize_payload(original, stored_assets if audio_assets is None else audio_assets)
            except Review:
                raise Review('normalization_metadata_conflict') from None
        else:
            regenerated, codes = normalize_payload(original, audio_assets)
        if not codes or regenerated != result:
            raise Review("normalization_metadata_conflict")
        return regenerated, codes
    ape = result.get("ape")
    if result.get("format") != "ape" or not isinstance(ape, dict) or ape.get("name") != "page":
        raise Review("normalization_source_invalid")
    original_ape, changed, table_changes = copy.deepcopy(ape), [], []
    ape, remaining_static_changes = normalize_remaining_static_material(
        ape, result.get('course_id'), result.get('lesson_id'), static_validator())
    ape, reviewed_player_changes = normalize_reviewed_legacy_players(
        ape, result.get('course_id'), result.get('lesson_id'), static_validator())
    ape, reviewed_image_rotations = normalize_reviewed_image_rotation(
        ape, result.get('course_id'), result.get('lesson_id'), static_validator())
    ape, missing_course_images = normalize_missing_course_images(
        ape, result.get('course_id'), result.get('lesson_id'), static_validator())
    ape, reviewed_material_changes = normalize_reviewed_static_material(
        ape, result.get('course_id'), result.get('lesson_id'), static_validator())
    ape, annotated_material_changes = normalize_annotated_material_buttons(
        ape, static_validator(), result.get('course_id'), result.get('lesson_id'))
    try:
        ape, owner_material_links = normalize_owner_material_links(ape, result.get('course_id'), result.get('lesson_id'))
    except Review as exc:
        if str(exc) == 'owner_material_source_invalid': raise Review('normalization_source_invalid') from None
        raise
    try:
        ape, owner_media_omissions = normalize_owner_media_omissions(ape, result.get('course_id'), result.get('lesson_id'))
    except Review as exc:
        if str(exc) == 'owner_media_ape_invalid': raise Review('normalization_source_invalid') from None
        raise
    ape, approved_image_omissions = normalize_approved_images(ape, result.get('course_id'), result.get('lesson_id'))
    ape, image_label_changes = normalize_image_labels(ape, static_validator())
    ape, video_value_changes = normalize_video_values(ape, static_validator())
    ape, video_source_changes = normalize_native_video_sources(ape, static_validator())
    ape, audio_changes = normalize_audio(ape, audio_assets)
    ape, stage_changes = normalize_stage_widgets(ape, static_validator())
    ape, accordion_changes = normalize_accordions(ape, static_validator())
    ape, editor_changes = normalize_nodes(ape, static_validator())
    ape, image_wrapper_changes = normalize_image_wrapper_layout(ape, static_validator())
    ape, image_changes = normalize_inline_images(ape, static_validator())
    ape, extracted_image_changes = normalize_nodes(ape, static_validator())
    editor_changes.extend(extracted_image_changes)
    ape, empty_button_changes = normalize_empty_material_buttons(
        ape, static_validator(), course_id=result.get('course_id'), lesson_id=result.get('lesson_id'))
    ape, button_changes = normalize_button_labels(ape, static_validator())
    ape, empty_widget_changes = normalize_empty_discussion_widgets(ape, static_validator())
    try:
        ape, presentation_changes = normalize_static_presentation(ape, static_validator())
    except Review as exc:
        if str(exc) != 'static_presentation_requires_review':
            raise
        # Keep earlier safe repairs; unknown HTML still reaches the core parser.
        presentation_changes = []
    try:
        ape, keyboard_changes = normalize_keyboard_markup(ape, static_validator())
    except Review as exc:
        if str(exc) != 'keyboard_markup_requires_review': raise
        keyboard_changes = []
    ape, link_metadata_changes = normalize_redundant_link_metadata(ape, static_validator())
    try:
        ape, legacy_decoration_changes = normalize_legacy_html_decorations(ape, static_validator())
    except Review as exc:
        if str(exc) != 'legacy_html_decoration_requires_review': raise
        legacy_decoration_changes = []
    if presentation_changes or link_metadata_changes or legacy_decoration_changes:
        ape, repaired_headers = normalize_nodes(ape, static_validator())
        editor_changes.extend(repaired_headers)
        ape, repaired_buttons = normalize_button_labels(ape, static_validator())
        button_changes.extend(repaired_buttons)
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
    if button_changes:
        codes.append(BUTTON_CODE)
    if accordion_changes:
        codes.append(ACCORDION_CODE)
    if stage_changes:
        codes.append(STAGE_CODE)
    if audio_changes:
        codes.append(AUDIO_CODE)
    if approved_image_omissions:
        codes.append(OMIT_IMAGE_CODE)
    if image_label_changes:
        codes.append(IMAGE_LABEL_CODE)
    if presentation_changes:
        codes.append(PRESENTATION_CODE)
    if empty_button_changes:
        codes.append(EMPTY_BUTTON_CODE)
    if video_value_changes:
        codes.append(VIDEO_VALUE_CODE)
    if empty_widget_changes:
        codes.append(EMPTY_WIDGET_CODE)
    if keyboard_changes:
        codes.append(KEYBOARD_CODE)
    if link_metadata_changes:
        codes.append(LINK_METADATA_CODE)
    if legacy_decoration_changes:
        codes.append(LEGACY_DECORATION_CODE)
    if video_source_changes:
        codes.append(VIDEO_SOURCE_CODE)
    if owner_media_omissions:
        codes.append(OWNER_MEDIA_CODE)
    if owner_material_links:
        codes.append(OWNER_MATERIAL_CODE)
    if image_wrapper_changes:
        codes.append(IMAGE_WRAPPER_CODE)
    if annotated_material_changes:
        codes.append(ANNOTATED_MATERIAL_CODE)
    codes.extend(dict.fromkeys(change['code'] for change in reviewed_material_changes))
    if missing_course_images:
        codes.extend(dict.fromkeys(change['code'] for change in missing_course_images))
    if reviewed_image_rotations:
        codes.append(REVIEWED_ROTATION_CODE)
    codes.extend(dict.fromkeys(change['code'] for change in remaining_static_changes))
    codes.extend(dict.fromkeys(change['code'] for change in reviewed_player_changes))
    if codes:
        result["source_original_ape"] = original_ape
        if (presentation_changes or empty_button_changes or video_value_changes or empty_widget_changes or keyboard_changes
                or link_metadata_changes or legacy_decoration_changes or video_source_changes or owner_media_omissions
                or owner_material_links or image_wrapper_changes or annotated_material_changes or reviewed_material_changes
                or missing_course_images or reviewed_image_rotations or remaining_static_changes or reviewed_player_changes):
            metadata = {"version": 10, "kind": "mastervision_editor_normalization", "codes": codes,
                        "blocks": changed, "table_blocks": table_changes, "editor_blocks": editor_changes,
                        "inline_image_blocks": image_changes, "button_blocks": button_changes,
                        "accordion_blocks": accordion_changes, "stage_blocks": stage_changes,
                        "approved_image_omissions": approved_image_omissions, "image_label_blocks": image_label_changes,
                        "presentation_blocks": presentation_changes, "empty_button_blocks": empty_button_changes,
                        "video_value_blocks": video_value_changes, "empty_widget_blocks": empty_widget_changes,
                        "keyboard_blocks": keyboard_changes}
            if link_metadata_changes or legacy_decoration_changes or video_source_changes:
                metadata.update(version=11, link_metadata_blocks=link_metadata_changes,
                                legacy_decoration_blocks=legacy_decoration_changes,
                                video_source_blocks=video_source_changes)
            if owner_media_omissions:
                metadata.update(version=12, owner_media_omissions=owner_media_omissions)
            if owner_material_links:
                metadata.update(version=13, owner_material_links=owner_material_links)
            if image_wrapper_changes:
                metadata.update(version=14, image_wrapper_blocks=image_wrapper_changes)
            if annotated_material_changes:
                metadata.update(version=15, annotated_material_blocks=annotated_material_changes)
            if reviewed_material_changes:
                metadata.update(version=16, reviewed_material_blocks=reviewed_material_changes)
            if missing_course_images:
                metadata.update(version=17, missing_course_images=missing_course_images)
            if reviewed_image_rotations:
                metadata.update(version=18, reviewed_image_rotations=reviewed_image_rotations)
            if any(change.get('http_status') == 403 for change in missing_course_images):
                metadata['version'] = 19
            if remaining_static_changes or reviewed_player_changes:
                metadata.update(version=20, remaining_static_blocks=remaining_static_changes,
                                reviewed_legacy_player_blocks=reviewed_player_changes)
            if audio_changes:
                metadata["audio_blocks"] = audio_changes
                metadata["audio_assets"] = {key: copy.deepcopy(audio_assets[key])
                    for key in sorted({change['url_sha256'] for change in audio_changes})}
            result["source_normalization"] = metadata
        elif image_label_changes:
            metadata = {"version": 9, "kind": "mastervision_editor_normalization", "codes": codes,
                        "blocks": changed, "table_blocks": table_changes, "editor_blocks": editor_changes,
                        "inline_image_blocks": image_changes, "button_blocks": button_changes,
                        "accordion_blocks": accordion_changes, "stage_blocks": stage_changes,
                        "approved_image_omissions": approved_image_omissions, "image_label_blocks": image_label_changes}
            if audio_changes:
                metadata["audio_blocks"] = audio_changes
                metadata["audio_assets"] = {key: copy.deepcopy(audio_assets[key])
                    for key in sorted({change['url_sha256'] for change in audio_changes})}
            result["source_normalization"] = metadata
        elif approved_image_omissions:
            metadata = {"version": 8, "kind": "mastervision_editor_normalization", "codes": codes,
                        "blocks": changed, "table_blocks": table_changes, "editor_blocks": editor_changes,
                        "inline_image_blocks": image_changes, "button_blocks": button_changes,
                        "accordion_blocks": accordion_changes, "stage_blocks": stage_changes,
                        "approved_image_omissions": approved_image_omissions}
            if audio_changes:
                metadata["audio_blocks"] = audio_changes
                metadata["audio_assets"] = {key: copy.deepcopy(audio_assets[key])
                    for key in sorted({change['url_sha256'] for change in audio_changes})}
            result["source_normalization"] = metadata
        elif audio_changes:
            used_assets = {key: copy.deepcopy(audio_assets[key])
                           for key in sorted({change['url_sha256'] for change in audio_changes})}
            result["source_normalization"] = {"version": 7, "kind": "mastervision_editor_normalization", "codes": codes,
                                               "blocks": changed, "table_blocks": table_changes, "editor_blocks": editor_changes,
                                               "inline_image_blocks": image_changes, "button_blocks": button_changes,
                                               "accordion_blocks": accordion_changes, "stage_blocks": stage_changes,
                                               "audio_blocks": audio_changes, "audio_assets": used_assets}
        elif stage_changes:
            result["source_normalization"] = {"version": 6, "kind": "mastervision_editor_normalization", "codes": codes,
                                               "blocks": changed, "table_blocks": table_changes, "editor_blocks": editor_changes,
                                               "inline_image_blocks": image_changes, "button_blocks": button_changes,
                                               "accordion_blocks": accordion_changes, "stage_blocks": stage_changes}
        elif accordion_changes:
            result["source_normalization"] = {"version": 5, "kind": "mastervision_editor_normalization", "codes": codes,
                                               "blocks": changed, "table_blocks": table_changes, "editor_blocks": editor_changes,
                                               "inline_image_blocks": image_changes, "button_blocks": button_changes,
                                               "accordion_blocks": accordion_changes}
        elif button_changes:
            result["source_normalization"] = {"version": 4, "kind": "mastervision_editor_normalization", "codes": codes,
                                               "blocks": changed, "table_blocks": table_changes, "editor_blocks": editor_changes,
                                               "inline_image_blocks": image_changes, "button_blocks": button_changes}
        elif image_changes:
            result["source_normalization"] = {"version": 3, "kind": "mastervision_editor_normalization", "codes": codes,
                                               "blocks": changed, "table_blocks": table_changes, "editor_blocks": editor_changes,
                                               "inline_image_blocks": image_changes}
        elif table_changes or editor_changes:
            result["source_normalization"] = {"version": 2, "kind": "mastervision_editor_normalization", "codes": codes,
                                               "blocks": changed, "table_blocks": table_changes, "editor_blocks": editor_changes}
        else:
            result["source_normalization"] = {"version": 1, "kind": "mastervision_single_iframe", "codes": [CODE], "blocks": changed}
    return result, codes
