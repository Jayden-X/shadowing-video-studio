"""Persistent immutable visual assets; browser names never become filesystem paths."""

import asyncio
import hashlib
import json
import os
import re
import shutil
import stat
import struct
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_DIMENSION = 8192
MAX_IMAGE_PIXELS = 20_000_000
MAX_VISUAL_LIBRARY_BYTES = 1024 * 1024 * 1024
MAX_VISUAL_RECORDS = 500
MAX_RECORD_BYTES = 8192
IMAGE_VALIDATION_SECONDS = 20
OPAQUE_ID = re.compile(r"[0-9a-f]{32}")
SHA256 = re.compile(r"[0-9a-f]{64}")
KINDS = {"background": "backgrounds", "illustration": "illustrations"}
EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
RECORD_KEYS = frozenset(
    {"version", "id", "kind", "name", "mimeType", "width", "height", "sizeBytes", "sha256"}
)


class VisualAssetError(Exception):
    def __init__(self, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class VisualImageProbe(Protocol):
    async def validate(self, path: Path, mime_type: str) -> tuple[int, int]: ...


@dataclass(frozen=True)
class VisualAsset:
    id: str
    kind: str
    name: str
    mime_type: str
    width: int
    height: int
    size_bytes: int
    sha256: str
    path: Path

    def dto(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "mimeType": self.mime_type,
            "width": self.width,
            "height": self.height,
            "sizeBytes": self.size_bytes,
            "available": True,
            "reason": None,
        }


def validate_dimensions(width: int, height: int) -> None:
    if (
        type(width) is not int
        or type(height) is not int
        or not 1 <= width <= MAX_IMAGE_DIMENSION
        or not 1 <= height <= MAX_IMAGE_DIMENSION
        or width * height > MAX_IMAGE_PIXELS
    ):
        raise VisualAssetError("Use an image up to 8192 pixels per side and 20 megapixels.")


def image_metadata(content: bytes) -> tuple[str, int, int]:
    """Read bounded raster headers before any decoder can allocate a large frame."""
    if not 0 < len(content) <= MAX_IMAGE_BYTES:
        raise VisualAssetError("Upload a nonempty image no larger than 10 MiB.", 413)
    try:
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            if len(content) < 45 or content[8:16] != b"\x00\x00\x00\rIHDR":
                raise ValueError
            width, height = struct.unpack_from(">II", content, 16)
            position = 8
            ended = False
            has_pixels = False
            while position + 12 <= len(content):
                size = struct.unpack_from(">I", content, position)[0]
                tag = content[position + 4 : position + 8]
                if (
                    size > len(content) - position - 12
                    or tag == b"acTL"
                    or (tag == b"IHDR" and position != 8)
                ):
                    raise ValueError
                has_pixels |= tag == b"IDAT"
                position += size + 12
                if tag == b"IEND":
                    if size or position != len(content):
                        raise ValueError
                    ended = True
                    break
            if not ended or not has_pixels:
                raise ValueError
            mime = "image/png"
        elif content.startswith(b"\xff\xd8"):
            position = 2
            dimensions = None
            while position < len(content):
                if content[position] != 0xFF:
                    raise ValueError
                while position < len(content) and content[position] == 0xFF:
                    position += 1
                marker = content[position]
                position += 1
                if marker in (0xD9, 0xDA):
                    break
                if marker == 0x01 or 0xD0 <= marker <= 0xD7:
                    continue
                size = struct.unpack_from(">H", content, position)[0]
                if size < 2 or size > len(content) - position:
                    raise ValueError
                if marker in {
                    0xC0,
                    0xC1,
                    0xC2,
                    0xC3,
                    0xC5,
                    0xC6,
                    0xC7,
                    0xC9,
                    0xCA,
                    0xCB,
                    0xCD,
                    0xCE,
                    0xCF,
                }:
                    if size < 8 or dimensions is not None:
                        raise ValueError
                    height, width = struct.unpack_from(">HH", content, position + 3)
                    dimensions = (width, height)
                position += size
            if dimensions is None or not content.endswith(b"\xff\xd9"):
                raise ValueError
            width, height = dimensions
            mime = "image/jpeg"
        elif content[:4] == b"RIFF" and content[8:12] == b"WEBP":
            if struct.unpack_from("<I", content, 4)[0] + 8 != len(content):
                raise ValueError
            position = 12
            dimensions = None
            has_pixels = False
            while position + 8 <= len(content):
                tag = content[position : position + 4]
                size = struct.unpack_from("<I", content, position + 4)[0]
                start = position + 8
                end = start + size
                if end > len(content) or tag in (b"ANIM", b"ANMF"):
                    raise ValueError
                payload = content[start:end]
                if tag == b"VP8X":
                    if len(payload) != 10 or payload[0] & 0x02 or dimensions is not None:
                        raise ValueError
                    dimensions = (
                        int.from_bytes(payload[4:7], "little") + 1,
                        int.from_bytes(payload[7:10], "little") + 1,
                    )
                elif tag == b"VP8L":
                    if len(payload) < 5 or payload[0] != 0x2F or has_pixels:
                        raise ValueError
                    bits = int.from_bytes(payload[1:5], "little")
                    decoded_dimensions = ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
                    validate_dimensions(*decoded_dimensions)
                    if dimensions is not None and dimensions != decoded_dimensions:
                        raise ValueError
                    dimensions = decoded_dimensions
                    has_pixels = True
                elif tag == b"VP8 ":
                    if len(payload) < 10 or payload[3:6] != b"\x9d\x01\x2a" or has_pixels:
                        raise ValueError
                    width, height = struct.unpack_from("<HH", payload, 6)
                    decoded_dimensions = (width & 0x3FFF, height & 0x3FFF)
                    validate_dimensions(*decoded_dimensions)
                    if dimensions is not None and dimensions != decoded_dimensions:
                        raise ValueError
                    dimensions = decoded_dimensions
                    has_pixels = True
                position = end + (size & 1)
            if position != len(content) or dimensions is None or not has_pixels:
                raise ValueError
            width, height = dimensions
            mime = "image/webp"
        else:
            raise ValueError
    except (ValueError, IndexError, struct.error) as exc:
        raise VisualAssetError("Upload a valid static PNG, JPEG, or WebP image.") from exc
    validate_dimensions(width, height)
    return mime, width, height


def _unsafe(path: Path) -> bool:
    return any(
        item.is_symlink() or getattr(item, "is_junction", lambda: False)()
        for item in (path, *path.parents)
    )


def _display_name(name: str) -> str:
    if not isinstance(name, str):
        raise VisualAssetError("Choose a filename for the uploaded image.")
    name = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if (
        not name
        or len(name) > 160
        or any(ord(char) < 32 or ord(char) == 127 or 0xD800 <= ord(char) <= 0xDFFF for char in name)
    ):
        raise VisualAssetError("Use an image filename of 1 to 160 characters without controls.")
    return name


def _strict_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


class VisualLibrary:
    def __init__(self, workspace: Path, probe: VisualImageProbe) -> None:
        self.workspace = workspace
        self.probe = probe
        self._import_lock = asyncio.Lock()
        self._validate_workspace()

    def _validate_workspace(self) -> None:
        if (
            not self.workspace.is_absolute()
            or not self.workspace.is_dir()
            or _unsafe(self.workspace)
            or self.workspace.resolve() != self.workspace
        ):
            raise VisualAssetError("Configure an existing visual workspace without links.", 503)

    def _directories(self) -> tuple[Path, Path]:
        self._validate_workspace()
        parent = self.workspace / "visuals"
        directories = tuple(parent / folder for folder in KINDS.values())
        try:
            for directory in (parent, *directories):
                if _unsafe(directory) or directory.resolve() != directory:
                    raise VisualAssetError("The local visual library directory is unsafe.", 503)
                directory.mkdir(mode=0o700, exist_ok=True)
                if not directory.is_dir():
                    raise VisualAssetError(
                        "The local visual library directory is unavailable.", 503
                    )
        except OSError as exc:
            raise VisualAssetError("Could not open the local visual library.", 503) from exc
        return directories

    def _record_directories(self) -> list[tuple[str, Path]]:
        result = []
        for kind, directory in zip(KINDS, self._directories(), strict=True):
            with os.scandir(directory) as entries:
                for entry in entries:
                    if len(result) >= MAX_VISUAL_RECORDS:
                        raise VisualAssetError(
                            "The visual library reached its 500-item limit.", 409
                        )
                    path = Path(entry.path)
                    if not OPAQUE_ID.fullmatch(entry.name) or _unsafe(path) or not path.is_dir():
                        raise VisualAssetError("The visual library contains an unsafe entry.", 503)
                    result.append((kind, path))
        return sorted(result, key=lambda item: item[1].name)

    def _storage_used(self, directories: list[tuple[str, Path]]) -> int:
        total = 0
        for _, directory in directories:
            with os.scandir(directory) as entries:
                count = 0
                for entry in entries:
                    count += 1
                    path = Path(entry.path)
                    if count > 2 or _unsafe(path):
                        raise VisualAssetError("The visual library contains an unsafe entry.", 503)
                    info = entry.stat(follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode):
                        raise VisualAssetError("The visual library contains an unsafe entry.", 503)
                    total += info.st_size
                    if total > MAX_VISUAL_LIBRARY_BYTES:
                        raise VisualAssetError("The visual library reached its 1 GiB limit.", 409)
        return total

    def _read_owned(self, path: Path, limit: int) -> bytes:
        self._validate_workspace()
        if not path.is_relative_to(self.workspace / "visuals") or _unsafe(path):
            raise VisualAssetError(
                "This image is unavailable. Select or upload another image.", 404
            )
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
                raise VisualAssetError(
                    "This image is invalid. Select or upload another image.", 404
                )
            content = handle.read(limit + 1)
        if len(content) != info.st_size or len(content) > limit:
            raise VisualAssetError("This image changed. Select or upload another image.", 404)
        return content

    def _record(self, directory: Path, kind: str) -> VisualAsset:
        try:
            record = json.loads(
                self._read_owned(directory / "asset.json", MAX_RECORD_BYTES),
                object_pairs_hook=_strict_object,
            )
            if (
                not isinstance(record, dict)
                or record.keys() != RECORD_KEYS
                or type(record["version"]) is not int
                or record["version"] != 1
                or record["id"] != directory.name
                or record["kind"] != kind
                or record["mimeType"] not in EXTENSIONS
                or not isinstance(record["sha256"], str)
                or not SHA256.fullmatch(record["sha256"])
                or type(record["sizeBytes"]) is not int
                or not 0 < record["sizeBytes"] <= MAX_IMAGE_BYTES
                or record["name"] != _display_name(record["name"])
            ):
                raise ValueError
            validate_dimensions(record["width"], record["height"])
            return VisualAsset(
                record["id"],
                kind,
                record["name"],
                record["mimeType"],
                record["width"],
                record["height"],
                record["sizeBytes"],
                record["sha256"],
                directory / f"image.{EXTENSIONS[record['mimeType']]}",
            )
        except (OSError, ValueError, TypeError, RecursionError, VisualAssetError) as exc:
            raise VisualAssetError(
                "This image record is invalid. Upload the image again.", 404
            ) from exc

    def _verified_content(self, asset: VisualAsset) -> bytes:
        try:
            content = self._read_owned(asset.path, MAX_IMAGE_BYTES)
            if (
                len(content) != asset.size_bytes
                or hashlib.sha256(content).hexdigest() != asset.sha256
            ):
                raise ValueError
            if image_metadata(content) != (asset.mime_type, asset.width, asset.height):
                raise ValueError
            return content
        except (OSError, ValueError, VisualAssetError) as exc:
            raise VisualAssetError(
                "This image is missing or changed. Select or upload another image.", 404
            ) from exc

    def list_assets(self) -> list[dict]:
        try:
            result = []
            for kind, directory in self._record_directories():
                try:
                    asset = self._record(directory, kind)
                except VisualAssetError:
                    # A sidecar is the registration commit. Incomplete imports and
                    # invalid records cannot supply a trustworthy UI identity/name.
                    continue
                item = asset.dto()
                try:
                    self._verified_content(asset)
                except VisualAssetError as exc:
                    item.update(available=False, reason=exc.detail)
                result.append(item)
            return result
        except OSError as exc:
            raise VisualAssetError("Could not read the local visual library.", 503) from exc

    def get(self, asset_id: str, kind: str | None = None) -> VisualAsset:
        if (
            not isinstance(asset_id, str)
            or not OPAQUE_ID.fullmatch(asset_id)
            or (kind is not None and kind not in KINDS)
        ):
            raise VisualAssetError("Image asset not found. Select or upload another image.", 404)
        try:
            for current_kind, directory in zip(KINDS, self._directories(), strict=True):
                if kind is not None and kind != current_kind:
                    continue
                candidate = directory / asset_id
                if candidate.exists():
                    asset = self._record(candidate, current_kind)
                    self._verified_content(asset)
                    return asset
        except OSError as exc:
            raise VisualAssetError(
                "This image is unavailable. Select or upload another image.", 404
            ) from exc
        raise VisualAssetError("Image asset not found. Select or upload another image.", 404)

    def read(self, asset_id: str, kind: str | None = None) -> bytes:
        return self._verified_content(self.get(asset_id, kind))

    def _allocate(self, kind: str, mime: str, content: bytes) -> tuple[str, Path]:
        directories = self._record_directories()
        used = self._storage_used(directories)
        if len(directories) >= MAX_VISUAL_RECORDS:
            raise VisualAssetError("The visual library reached its 500-item limit.", 409)
        reserve = len(content) + MAX_RECORD_BYTES
        if used + reserve > MAX_VISUAL_LIBRARY_BYTES:
            raise VisualAssetError("The visual library reached its 1 GiB limit.", 409)
        if shutil.disk_usage(self.workspace).free < reserve:
            raise VisualAssetError("Free disk space before uploading another image.", 409)
        asset_id = uuid.uuid4().hex
        parent = self.workspace / "visuals" / KINDS[kind]
        directory = parent / asset_id
        if _unsafe(parent) or parent.resolve() != parent:
            raise VisualAssetError("The local visual library directory changed.", 503)
        directory.mkdir(mode=0o700)
        destination = directory / f"image.{EXTENSIONS[mime]}"
        with destination.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return asset_id, destination

    def _register(self, asset: VisualAsset) -> None:
        self._verified_content(asset)
        record = {
            "version": 1,
            "id": asset.id,
            "kind": asset.kind,
            "name": asset.name,
            "mimeType": asset.mime_type,
            "width": asset.width,
            "height": asset.height,
            "sizeBytes": asset.size_bytes,
            "sha256": asset.sha256,
        }
        content = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(content) > MAX_RECORD_BYTES:
            raise VisualAssetError("The image registration metadata exceeded its limit.")
        with (asset.path.parent / "asset.json").open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

    async def import_asset(self, kind: str, name: str, content: bytes) -> VisualAsset:
        if not isinstance(kind, str) or kind not in KINDS:
            raise VisualAssetError("Choose background or illustration for the image.")
        name = _display_name(name)
        if not isinstance(content, bytes):
            raise VisualAssetError("Upload image bytes rather than a local path.")
        mime, width, height = await asyncio.to_thread(image_metadata, content)
        async with self._import_lock:
            try:
                asset_id, path = await asyncio.to_thread(self._allocate, kind, mime, content)
                async with asyncio.timeout(IMAGE_VALIDATION_SECONDS):
                    decoded_width, decoded_height = await self.probe.validate(path, mime)
                if (decoded_width, decoded_height) != (width, height):
                    raise VisualAssetError("The image metadata does not match its decoded content.")
                asset = VisualAsset(
                    asset_id,
                    kind,
                    name,
                    mime,
                    width,
                    height,
                    len(content),
                    hashlib.sha256(content).hexdigest(),
                    path,
                )
                await asyncio.to_thread(self._register, asset)
                return asset
            except TimeoutError as exc:
                raise VisualAssetError(
                    "Image validation timed out. Try a smaller image.", 422
                ) from exc
            except OSError as exc:
                raise VisualAssetError(
                    "Could not store the image. Check local free space.", 503
                ) from exc
