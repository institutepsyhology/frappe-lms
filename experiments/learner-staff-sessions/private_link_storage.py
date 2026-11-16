"""Windows user-bound DPAPI storage for the private API preflight archive."""
import ctypes
from ctypes import wintypes
import base64
import hashlib
import json
import os
import threading
from server_archive_sink import PROFILE


class StorageError(Exception):
    pass


_SERVER_CIPHER = None
_SERVER_CIPHER_LOCK = threading.Lock()


def configure_server_cipher(cipher, account):
    """Bind one existing site cipher once, before a dedicated server job starts.

    The caller supplies a Fernet-compatible object from the selected site's
    EXISTING key. Windows jobs retain DPAPI unless explicitly injected in tests.
    No key is loaded from CLI/environment or created by this module.
    """
    global _SERVER_CIPHER
    if account != PROFILE.account:
        raise StorageError('server_cipher_wrong_account')
    if not callable(getattr(cipher, 'encrypt', None)) or not callable(getattr(cipher, 'decrypt', None)):
        raise StorageError('server_cipher_invalid')
    with _SERVER_CIPHER_LOCK:
        if _SERVER_CIPHER is not None:
            raise StorageError('server_cipher_already_configured')
        _SERVER_CIPHER = cipher


def _server_crypt(source_id, data, decrypt):
    try:
        binding = {'format': 'avo-server-private-storage-v1', 'account': PROFILE.account,
                   'namespace': PROFILE.crypto_namespace, 'source_id': source_id}
        if decrypt:
            envelope = json.loads(_SERVER_CIPHER.decrypt(data).decode('ascii'))
            if (not isinstance(envelope, dict) or set(envelope) != set(binding) | {'data_b64'}
                    or any(envelope.get(key) != value for key, value in binding.items())
                    or type(envelope.get('source_id')) is not int
                    or not isinstance(envelope.get('data_b64'), str)):
                raise StorageError('private_link_crypto_failed')
            return base64.b64decode(envelope['data_b64'], validate=True)
        envelope = dict(binding, data_b64=base64.b64encode(data).decode('ascii'))
        raw = json.dumps(envelope, ensure_ascii=True, sort_keys=True,
                         separators=(',', ':')).encode('ascii')
        encrypted = _SERVER_CIPHER.encrypt(raw)
        if not isinstance(encrypted, bytes) or not encrypted:
            raise StorageError('private_link_crypto_failed')
        return encrypted
    except Exception:
        raise StorageError('private_link_crypto_failed') from None


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data):
    buffer = ctypes.create_string_buffer(data)
    return Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def _crypt(source_id, data, decrypt=False):
    if type(source_id) is not int or not 0 < source_id < 2**63 or not isinstance(data, bytes):
        raise StorageError('private_link_storage_unavailable')
    if _SERVER_CIPHER is not None:
        return _server_crypt(source_id, data, decrypt)
    if os.name != 'nt':
        raise StorageError('private_link_storage_unavailable')
    source, source_buffer = _blob(data)
    entropy, entropy_buffer = _blob(hashlib.sha256(
        (PROFILE.crypto_namespace + str(source_id)).encode('ascii')).digest())
    output = Blob()
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    description_type = ctypes.POINTER(wintypes.LPWSTR) if decrypt else wintypes.LPCWSTR
    function.argtypes = [ctypes.POINTER(Blob), description_type, ctypes.POINTER(Blob),
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(source), None, ctypes.byref(entropy), None, None, 1, ctypes.byref(output)):
        raise StorageError('private_link_crypto_failed')
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel32.LocalFree(output.data)


def protect_url(source_id, url):
    if not isinstance(url, str) or not url:
        raise StorageError('invalid_private_link')
    return _crypt(source_id, url.encode('utf-8'))


def unprotect_url(source_id, value):
    if isinstance(value,bytes) and value.startswith(PROFILE.remote_prefix):
        raise StorageError('private_link_stored_on_frappe')
    return _crypt(source_id, value, decrypt=True).decode('utf-8')
