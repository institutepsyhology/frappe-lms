"""Windows user-bound DPAPI storage for the private API preflight archive."""
import ctypes
from ctypes import wintypes
import hashlib
import os


class StorageError(Exception):
    pass


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data):
    buffer = ctypes.create_string_buffer(data)
    return Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def _crypt(source_id, data, decrypt=False):
    if os.name != 'nt' or type(source_id) is not int or not 0 < source_id < 2**63 or not isinstance(data, bytes):
        raise StorageError('private_link_storage_unavailable')
    source, source_buffer = _blob(data)
    entropy, entropy_buffer = _blob(hashlib.sha256(
        ('AVO-MVC-Learner-Link-v1:' + str(source_id)).encode('ascii')).digest())
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
    if isinstance(value,bytes) and value.startswith(b'REMOTE:MVC-FRAPPE:v1:'):
        raise StorageError('private_link_stored_on_frappe')
    return _crypt(source_id, value, decrypt=True).decode('utf-8')
