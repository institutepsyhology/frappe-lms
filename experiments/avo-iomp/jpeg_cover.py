"""Prepare JPEG attachments before sending a File mutation to IOMP."""

import io

from assets import _inspect
from covers import strip_jpeg_for_storage
from importer import Review, Stop


def prepare_jpeg_upload(raw):
    """Return the exact bytes expected back from Frappe, with orientation applied.

    Keep the original SHA-256 for the attachment filename. Use the returned
    bytes for the upload and for both File read-back checks (length and MD5).
    """
    try:
        from PIL import Image
    except ImportError:
        raise Review('cover_transform_requires_pillow') from None
    if _inspect(raw) != 'jpg':
        raise Review('cover_image_type_mismatch')
    try:
        stripped = strip_jpeg_for_storage(raw)
        prepared = raw if stripped is None else stripped
        if stripped is not None and _inspect(prepared) != 'jpg':
            raise Review('cover_jpeg_preparation_invalid')
        with Image.open(io.BytesIO(prepared)) as image:
            if image.format != 'JPEG' or image.getexif():
                raise Review('cover_jpeg_preparation_invalid')
            image.load()
    except (Stop, OSError, ValueError):
        raise Review('cover_jpeg_preparation_invalid') from None
    return prepared
