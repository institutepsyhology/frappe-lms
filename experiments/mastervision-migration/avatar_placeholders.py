"""Recognize only confirmed public default avatars; never fetch their URLs."""
import re
import unicodedata
from urllib.parse import unquote, urlsplit


def _decoded_safe_path(path):
    """Validate one UTF-8 decoding without authorizing another host or URL."""
    if (not isinstance(path, str) or not path.startswith('/') or len(path) > 8192
            or re.search(r'[\x00-\x20\x7f\\]', path)
            or re.search(r'%(?![0-9a-fA-F]{2})', path)
            or re.search(r'%(?:2f|5c)', path, re.I)):
        return None
    try:
        decoded = unquote(path, encoding='utf-8', errors='strict')
    except UnicodeError:
        return None
    if ('%' in decoded or any(char in decoded for char in '\\?#')
            or any(unicodedata.category(char).startswith('C') for char in decoded)):
        return None
    segments = decoded.split('/')[1:]
    if not segments or any(not part or part.startswith('.') for part in segments):
        return None
    return decoded


def is_known_avatar_url(value):
    """Match confirmed unnamed/default profile images, preserving real images."""
    if (not isinstance(value, str) or not value or len(value) > 8192
            or re.search(r'[\x00-\x20\x7f\\?#]', value)):
        return False
    try:
        url = urlsplit(value)
        if (url.scheme != 'https' or url.username is not None or url.password is not None
                or url.port is not None or url.query or url.fragment):
            return False
    except ValueError:
        return False
    if url.hostname == 'getcourse.ru':
        return url.path == '/public/img/default_profile_50.png'
    if url.hostname != 'f1.autoweboffice.ru':
        return False
    path = _decoded_safe_path(url.path)
    return bool(path and path.rsplit('/', 1)[-1] == 'unnamed.jpeg'
                and url.path.rsplit('/', 1)[-1] == 'unnamed.jpeg')
