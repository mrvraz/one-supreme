"""Checks and cleans uploaded photos and videos before they are stored."""

import os
import shutil
import subprocess
import tempfile
import uuid
from io import BytesIO

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files import File
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

IMAGE_MAX_MB = 15
# A small file can still unpack huge: 13,000 x 13,000 pixels needs ~680 MB. This allows 48-megapixel phone photos.
IMAGE_MAX_PIXELS = 50_000_000
VIDEO_MAX_MB = 100
# Below this share of free disk space, uploads stop so the database never runs out of room.
MIN_FREE_DISK = 0.05
WEBM_MAGIC = b"\x1a\x45\xdf\xa3"
# These containers start like a video ("ftyp") but hold still images (iPhone HEIC, AVIF).
IMAGE_BRANDS = {b"heic", b"heix", b"hevc", b"mif1", b"msf1", b"avif", b"avis"}
VIDEO_FORMATS = {".mp4": "mp4", ".mov": "mov", ".webm": "webm"}


def disk_free_share():
    usage = shutil.disk_usage(settings.DATA_DIR)
    return usage.free / usage.total


def process_upload(upload, max_side=2048, video=True):
    """Return (file, kind) for a valid photo or video, or raise ValidationError.

    Photos are resized and re-encoded and videos are copied without their metadata, which drops data such as
    the GPS location where they were taken. With video=False only pictures are accepted, and a video is refused
    before any work is done on it.
    """
    if disk_free_share() < MIN_FREE_DISK:
        raise ValidationError("Uploads are paused because the server is nearly full. IT has been alerted.")
    head = upload.read(12)
    upload.seek(0)
    is_mp4_family = head[4:8] == b"ftyp" and head[8:12] not in IMAGE_BRANDS
    if is_mp4_family or head[:4] == WEBM_MAGIC:
        if not video:
            raise ValidationError("This needs a picture, not a video.")
        if upload.size > VIDEO_MAX_MB * 1024 * 1024:
            raise ValidationError(f"Videos must be under {VIDEO_MAX_MB} MB.")
        ext = ".webm" if head[:4] == WEBM_MAGIC else ".mov" if head[8:10] == b"qt" else ".mp4"
        return strip_video(upload, ext), "video"

    if upload.size > IMAGE_MAX_MB * 1024 * 1024:
        raise ValidationError(f"Photos must be under {IMAGE_MAX_MB} MB.")
    try:
        img = Image.open(upload)  # reads only the header, so the size is known before the memory is spent
        if img.width * img.height > IMAGE_MAX_PIXELS:
            raise ValidationError(f"Photos can be up to {IMAGE_MAX_PIXELS // 1_000_000} megapixels.")
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        kinds = "JPEG, PNG, GIF, MP4 or WebM" if video else "JPEG, PNG or GIF"
        raise ValidationError(f"That file isn't one we can use. Try {kinds}.")

    if img.format == "GIF" and getattr(img, "is_animated", False):
        upload.seek(0)  # keep the animation; GIFs don't carry camera location data
        upload.name = uuid.uuid4().hex + ".gif"
        return upload, "image"

    img = ImageOps.exif_transpose(img)
    img.thumbnail((max_side, max_side))
    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    # Keep the colour profile (no personal data in it): without it, iPhone photos look washed out.
    colours = {"icc_profile": img.info["icc_profile"]} if img.info.get("icc_profile") else {}
    out = BytesIO()
    if has_alpha:
        img.save(out, "PNG", optimize=True, **colours)
        ext = ".png"
    else:
        img.convert("RGB").save(out, "JPEG", quality=85, optimize=True, **colours)
        ext = ".jpg"
    return ContentFile(out.getvalue(), name=uuid.uuid4().hex + ext), "image"


def strip_video(upload, ext):
    """Copy the video and its sound into a new file, leaving behind all metadata (location, device, titles).

    The picture isn't re-encoded, so this takes seconds. A file ffmpeg can't read is rejected.
    shortcut: no conversion between formats, so an iPhone HEVC video may not play in every browser;
    add background transcoding if staff report playback problems.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:  # never store a video we couldn't clean
        raise ValidationError("Video uploads aren't available on this server yet.")
    workdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    source, target = os.path.join(workdir.name, "in" + ext), os.path.join(workdir.name, "out" + ext)
    with open(source, "wb") as fh:
        for chunk in upload.chunks():
            fh.write(chunk)
    fmt = VIDEO_FORMATS[ext]
    command = [
        ffmpeg, "-v", "error", "-nostdin", "-y", "-i", source,
        "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
        "-map_metadata", "-1", "-map_metadata:s:v", "-1", "-map_metadata:s:a", "-1", "-map_chapters", "-1",
        "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
    ]
    if fmt != "webm":
        command += ["-movflags", "+faststart"]  # lets the video start playing before it has fully downloaded
    try:
        subprocess.run(command + ["-f", fmt, target], check=True, capture_output=True, timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        workdir.cleanup()
        raise ValidationError("We couldn't read that video. Try an MP4, MOV or WebM file.")
    os.remove(source)
    cleaned = File(open(target, "rb"), name=uuid.uuid4().hex + ext)
    cleaned.workdir = workdir  # removed by PostForm.save() once stored, or when garbage-collected
    return cleaned
