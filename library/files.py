"""Checks uploaded documents before they are stored. The content must match the file name's ending,
so a program or web page renamed to ".pdf" is refused."""

import codecs
import os
import re
import uuid

from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

from hub import media

MAX_MB = 50
OLE = b"\xd0\xcf\x11\xe0"  # how the older Office files (.doc, .xls, .ppt) start
# Ending -> the bytes a real file of that type starts with.
MAGIC = {".pdf": b"%PDF", ".docx": b"PK", ".xlsx": b"PK", ".pptx": b"PK", ".doc": OLE, ".xls": OLE, ".ppt": OLE}
TEXT = {".txt", ".csv"}
IMAGES = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".gif": "GIF", ".webp": "WEBP"}
ALLOWED = {*MAGIC, *TEXT, *IMAGES, ".mp4"}


def _is_text(upload):
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        for chunk in upload.chunks():
            if b"\0" in chunk:
                return False
            decoder.decode(chunk)
        decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        return False
    return True


def _is_image(upload, expected):
    try:
        return Image.open(upload).format == expected
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return False


def check_document(upload):
    """Return `upload` under a random name (same ending), or raise ValidationError with a message for the person."""
    ext = os.path.splitext(upload.name)[1].lower()
    if ext not in ALLOWED:
        raise ValidationError("That type of file can't be added. Use PDF, Word, Excel, PowerPoint, text, CSV, a picture or MP4.")
    if not upload.size:
        raise ValidationError("That file is empty.")
    if upload.size > MAX_MB * 1024 * 1024:
        raise ValidationError(f"Files must be under {MAX_MB} MB.")
    if media.disk_free_share() < media.MIN_FREE_DISK:
        raise ValidationError("Uploads are paused because the server is nearly full. IT has been alerted.")
    head = upload.read(12)
    upload.seek(0)
    if ext in MAGIC:
        real = head.startswith(MAGIC[ext])
    elif ext == ".mp4":
        real = head[4:8] == b"ftyp"
    elif ext in TEXT:
        real = _is_text(upload)
    else:
        real = _is_image(upload, IMAGES[ext])
    if not real:
        raise ValidationError(f"That doesn't look like a real {ext[1:].upper()} file. Check the file and try again.")
    upload.seek(0)
    upload.name = uuid.uuid4().hex + ext
    return upload


def download_name(name):
    """The file name without folder separators or control characters, safe to offer as a download name."""
    return re.sub(r"[\x00-\x1f\x7f/\\]", "", name)
