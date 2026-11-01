"""Image uploads: only real JPG / PNG / WEBP images up to 5 MB.

Each image is opened with Pillow (so a renamed .exe or script is rejected), then
re-saved as a fresh JPEG. Re-saving removes hidden metadata like GPS location.

* Item photos: the full photo is kept private (private_uploads/items/). The public copy
  in static/uploads/ is blurred for found items, so only the real owner knows the details.
* Claim proofs: private only (private_uploads/proofs/), served after a permission check.
"""
import io
import os
import re
import uuid
import warnings

from flask import current_app
from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
FILE_ID_RE = re.compile(r"^[0-9a-f]{32}$")

Image.MAX_IMAGE_PIXELS = 15_000_000  # Stricter memory guard against pixel decompression bombs  # refuse "decompression bomb" images


class UploadError(ValueError):
    pass


def _load_image(file_storage):
    filename = file_storage.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadError("Only JPG, PNG or WEBP images are allowed.")

    limit = current_app.config["MAX_IMAGE_BYTES"]
    data = file_storage.stream.read(limit + 1)
    if len(data) > limit:
        raise UploadError(f"Each image must be {limit // (1024 * 1024)} MB or smaller.")
    if not data:
        raise UploadError("The uploaded file is empty.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as probe:
                if probe.format not in ALLOWED_FORMATS:
                    raise UploadError("Only JPG, PNG or WEBP images are allowed.")
                probe.verify()
            image = Image.open(io.BytesIO(data))
            image.load()
    except UploadError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning,
            OSError, SyntaxError, ValueError):
        raise UploadError("That file isn't a valid image.") from None

    image = ImageOps.exif_transpose(image)
    return _to_rgb(image)


def _to_rgb(image):
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        image = image.convert("RGBA")
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1])
        return background
    return image.convert("RGB")


def _private_dir(kind):
    path = os.path.join(current_app.config["PRIVATE_UPLOAD_FOLDER"], kind)
    os.makedirs(path, exist_ok=True)
    return path


def _public_dir():
    path = current_app.config["PUBLIC_UPLOAD_FOLDER"]
    os.makedirs(path, exist_ok=True)
    return path


def save_item_image(file_storage, blur):
    image = _load_image(file_storage)
    image_id = uuid.uuid4().hex

    original = image.copy()
    original.thumbnail((1600, 1600))
    original.save(os.path.join(_private_dir("items"), f"{image_id}.jpg"), "JPEG", quality=88, optimize=True)

    public = image.copy()
    if blur:
        # Small and blurred: you can tell the colour and shape, not the brand or contents.
        public.thumbnail((480, 480))
        public = public.filter(ImageFilter.GaussianBlur(radius=10))
    else:
        public.thumbnail((900, 900))
    public.save(os.path.join(_public_dir(), f"{image_id}.jpg"), "JPEG", quality=80, optimize=True)
    return image_id


def save_proof_image(file_storage):
    image = _load_image(file_storage)
    file_id = uuid.uuid4().hex
    image.thumbnail((1600, 1600))
    image.save(os.path.join(_private_dir("proofs"), f"{file_id}.jpg"), "JPEG", quality=88, optimize=True)
    return file_id


def private_path(kind, file_id):
    """Folder and filename for a private file, or (None, None) if the id looks wrong."""
    if kind not in ("items", "proofs") or not FILE_ID_RE.match(file_id or ""):
        return None, None
    return _private_dir(kind), f"{file_id}.jpg"
