"""用户头像处理：校验、缩放、ETag/缓存工具。

头像按方案存数据库（users.avatar_data），上传时统一缩放到 256x256 的 WEBP，
避免把原始大图写库。
"""
from __future__ import annotations

import hashlib
import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_AVATAR_BYTES = 200 * 1024          # 上传上限 200KB
AVATAR_SIZE = 256                      # 输出 256x256
OUTPUT_CONTENT_TYPE = "image/webp"
OUTPUT_QUALITY = 85


class AvatarValidationError(ValueError):
    """头像不合法（类型/大小/内容）。"""


def process_avatar(raw: bytes) -> tuple[bytes, str]:
    """校验并缩放到 256x256 WEBP，返回 (bytes, content_type)。"""
    if not raw:
        raise AvatarValidationError("头像文件为空")
    if len(raw) > MAX_AVATAR_BYTES:
        raise AvatarValidationError(f"头像不能超过 {MAX_AVATAR_BYTES // 1024}KB")

    try:
        image = Image.open(io.BytesIO(raw))
        image.seek(0)               # 动图只取第一帧
        image.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise AvatarValidationError("不支持的图片格式或图片已损坏") from exc
    except Image.DecompressionBombError as exc:
        raise AvatarValidationError("图片尺寸过大") from exc

    # 保留透明通道（PNG/WEBP），其余转 RGB
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        image = image.convert("RGBA")
    else:
        image = image.convert("RGB")

    image = ImageOps.fit(image, (AVATAR_SIZE, AVATAR_SIZE), method=Image.LANCZOS)

    buf = io.BytesIO()
    image.save(buf, "WEBP", quality=OUTPUT_QUALITY, method=6)
    data = buf.getvalue()
    if len(data) > MAX_AVATAR_BYTES:
        # 极端情况下降质量，仍保证不超过上限
        buf = io.BytesIO()
        image.save(buf, "WEBP", quality=60, method=6)
        data = buf.getvalue()
    return data, OUTPUT_CONTENT_TYPE


def avatar_url(user) -> str | None:
    """对外返回的头像 URL：库内头像带版本号，便于缓存失效。"""
    if getattr(user, "avatar_data", None):
        version = getattr(user, "avatar_version", 0) or 0
        return f"/api/v1/users/{user.id}/avatar?v={version}"
    return getattr(user, "avatar", None) or None


def avatar_etag(user) -> str:
    digest = hashlib.sha256(getattr(user, "avatar_data", b"") or b"").hexdigest()[:16]
    version = getattr(user, "avatar_version", 0) or 0
    return f'"{version}-{len(getattr(user, "avatar_data", b"") or b"")}-{digest}"'
