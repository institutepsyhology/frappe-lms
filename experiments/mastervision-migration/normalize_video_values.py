"""Repair only validated native video values; the caller keeps original APE."""
import copy

from importer import Review
from normalize_editor_nodes import _core, _style_content

CODE = 'native_video_values_normalized'
ASCII_SPACE = ' \t\r\n\v\f'
PROVIDERS = {'youtube', 'rutube'}
FLAGS = {'nativePlayer', 'nativePlayer2', 'isShowProgressControl', 'isShowProgressControl2',
         'isShowFastRewindButtons', 'isShowFastRewindButtons2', 'isFloating'}
PAIRED_FLAGS = ('nativePlayer', 'isShowProgressControl', 'isShowFastRewindButtons')
ALLOWED = FLAGS | {'videoSrc', 'videoSrc2', 'videoProvider', 'videoProvider2', 'anchor',
                   'embeddedHtml', 'posterSrc', 'posterSrc2', 'html'}


def _visible(fields):
    return any(fields.get(key) not in (None, '', False, [], {})
               for key in ('visibleConditions', 'displayDelay'))


def _eligible(node, validate):
    fields = node['fields']
    if (set(fields) - ALLOWED or node.get('children', [])
            or set(node) - {'id', 'name', 'fields', 'children', 'style'}
            or any(fields.get(key) not in (None, '')
                   for key in ('anchor', 'embeddedHtml', 'posterSrc', 'posterSrc2'))
            or any(fields.get(key) not in (None, '', 'youtube', 'rutube')
                   for key in ('videoProvider', 'videoProvider2'))
            or any(fields[key] not in (None, '', False, True, 0, 1, '0', '1') for key in FLAGS & set(fields))
            or any(fields.get(key) is not None and not isinstance(fields[key], str)
                   for key in ('videoSrc', 'videoSrc2', 'html'))
            or _style_content(node.get('style'))):
        return False
    caption = fields.get('html')
    if isinstance(caption, str) and '<' in caption:
        try: validate(caption)
        except (TypeError, ValueError, UnicodeError, RecursionError): return False
    return True


def normalize_video_values(ape, validate_static):
    """Return copied APE and metadata-only changes, never guess video identities."""
    if (not callable(validate_static) or not isinstance(ape, dict) or ape.get('name') != 'page'
            or not isinstance(ape.get('children'), list)):
        raise Review('video_values_source_invalid')
    copied, changes, visited = copy.deepcopy(ape), [], 0
    def walk(node, path, protected=False):
        nonlocal visited
        visited += 1
        if (visited > 150000 or len(path) > 100 or not isinstance(node, dict)
                or not isinstance(node.get('name'), str) or not isinstance(node.get('fields', {}), dict)
                or not isinstance(node.get('children', []), list)):
            raise Review('video_values_source_invalid')
        fields = node.get('fields', {})
        protected = protected or _visible(fields)
        if not protected and node['name'] == 'video' and 'fields' in node and _eligible(node, validate_static):
            trimmed = []
            for slot, suffix in ((1, ''), (2, '2')):
                key, provider = 'videoSrc' + suffix, fields.get('videoProvider' + suffix)
                original = fields.get(key)
                if not isinstance(original, str) or provider not in PROVIDERS: continue
                candidate = original.strip(ASCII_SPACE)
                if candidate != original and _core()._player_url(candidate, provider):
                    fields[key] = candidate; trimmed.append(slot)
            promoted = False; moved_flags = []
            provider, secondary = fields.get('videoProvider2'), fields.get('videoSrc2')
            if (fields.get('videoSrc') in (None, '') and provider in PROVIDERS
                    and _core()._player_url(secondary, provider)):
                fields['videoSrc'], fields['videoProvider'] = secondary, provider
                fields['videoSrc2'] = ''
                # Keep inactive secondary metadata, and copy its exact controls
                # (including False/0) into the now-active primary slot.
                for key in PAIRED_FLAGS:
                    if key + '2' in fields:
                        fields[key] = fields[key + '2']; moved_flags.append(key)
                promoted = True
            if trimmed or promoted:
                change = {'path': list(path), 'code': CODE}
                if trimmed: change['trimmed_slots'] = trimmed
                if promoted:
                    change['secondary_promoted'] = True
                    change['promoted_flags'] = moved_flags
                changes.append(change)
        child_protected = protected or node['name'] == 'video' and bool(node.get('children'))
        for index, child in enumerate(node.get('children', [])):
            walk(child, path + (index,), child_protected)
    walk(copied, ())
    return copied, changes
