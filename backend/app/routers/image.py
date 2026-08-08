"""
画像生成エンドポイント。

優先順位:
1. gallery / gallery-hybrid → ローカル LoRA ストック (img/stock_web → img/stock)
2. Cloudflare Workers AI (cf-sdxl / cf-flux)
3. Pollinations.ai へのリダイレクト（フォールバック）
"""
from __future__ import annotations

import hashlib
import os
import re
import urllib.parse
from pathlib import Path

import httpx
from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse, Response

from app.routers.settings import app_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

CF_MODELS = {
    "cf-sdxl": "@cf/bytedance/stable-diffusion-xl-lightning",
    "cf-flux": "@cf/black-forest-labs/flux-1-schnell",
}

# プロンプト内キーワード → ファイル名テーマ (kairi_{theme}_*.png)
_THEME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "school": (
        "school", "classroom", "uniform", "blazer", "bowtie", "chalkboard",
        "desk", "sailor",
    ),
    "beach": (
        "beach", "ocean", "sea", "swimsuit", "bikini", "palm", "sunset",
        "water", "pool",
    ),
    "room": (
        "bedroom", "room", "indoors", "hoodie", "bed", "selfie", "home",
    ),
    "casual": (
        "cafe", "street", "city", "casual", "sweater", "jacket", "crosswalk",
        "building", "night",
    ),
    "happening": (
        "happening", "accident",
    ),
}

# happening は低頻度枠なので、明示要求が無い限り候補から外す
_THEME_PRIORITY = ("school", "beach", "room", "casual", "happening")


def _repo_root() -> Path:
    # backend/app/routers/image.py → repo root
    return Path(__file__).resolve().parent.parent.parent.parent


def _stock_dirs() -> list[Path]:
    """本番は WebP 圧縮済み stock_web を優先。無ければローカル PNG stock にフォールバック。"""
    root = _repo_root()
    stock_web = root / "img" / "stock_web"
    stock_png = root / "img" / "stock"
    dirs: list[Path] = []
    # stock_web に1枚でもあれば PNG 側は読まない（同名stemの二重登録を防ぐ）
    if stock_web.exists() and any(stock_web.glob("*.webp")):
        dirs.append(stock_web)
    elif stock_png.exists():
        dirs.append(stock_png)
    dirs.extend(
        [
            root / "frontend" / "public" / "gallery",
            root / "backend" / "static" / "gallery",
        ]
    )
    return dirs


def _list_stock_images() -> list[Path]:
    images: list[Path] = []
    for d in _stock_dirs():
        if not d.exists():
            continue
        images.extend(d.rglob("*.png"))
        images.extend(d.rglob("*.jpg"))
        images.extend(d.rglob("*.jpeg"))
        images.extend(d.rglob("*.webp"))
    # 安定した順序（決定的選択の前提）
    return sorted({p.resolve() for p in images}, key=lambda p: str(p).lower())


def _keyword_hit(text: str, keyword: str) -> bool:
    """部分文字列誤爆（school⊂classroom）を避けるため単語境界で判定。"""
    return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None


def _detect_theme(prompt: str) -> str | None:
    """プロンプトから最も確からしいシチュエーションテーマを推定する。"""
    text = prompt.lower()
    scores: dict[str, int] = {}
    for theme, keywords in _THEME_KEYWORDS.items():
        score = sum(1 for kw in keywords if _keyword_hit(text, kw))
        if score:
            scores[theme] = score
    if not scores:
        return None
    # 同点なら優先度順
    best = max(scores.values())
    for theme in _THEME_PRIORITY:
        if scores.get(theme) == best:
            return theme
    return max(scores, key=scores.get)


def _theme_of_file(path: Path) -> str | None:
    """kairi_school_....png → school"""
    name = path.stem.lower()
    m = re.match(r"kairi_([a-z]+)_", name)
    if m:
        return m.group(1)
    for theme in _THEME_PRIORITY:
        if theme in name:
            return theme
    return None


def _select_stock_image(prompt: str, images: list[Path]) -> Path | None:
    """
    プロンプトに合うストックを選び、同じプロンプトでは常に同じ画像を返す。
    """
    if not images:
        return None

    theme = _detect_theme(prompt)
    pool = images
    if theme:
        themed = [p for p in images if _theme_of_file(p) == theme]
        # happening 以外でテーマ一致が無ければ全体から。happening 明示時のみ happening を使う
        if themed:
            pool = themed
        elif theme != "happening":
            # TPO無視のハプニング枠は通常会話では出さない
            pool = [p for p in images if _theme_of_file(p) != "happening"] or images
    else:
        # シチュ不明時も happening は出さない
        pool = [p for p in images if _theme_of_file(p) != "happening"] or images

    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    idx = int(digest[:8], 16) % len(pool)
    return pool[idx]


@router.get("/image/generate")
async def generate_image(
    prompt: str = Query(..., description="画像生成英語プロンプト"),
    width: int = Query(512, description="画像幅"),
    height: int = Query(512, description="画像高さ"),
):
    """
    設定されたエンジンに基づいて画像を返す。
    - gallery: ローカルストックのみ（無ければフォールバック）
    - gallery-hybrid: 80%ストック / 20%クラウド
    - pollinations / cf-*: クラウド生成
    """
    settings = app_settings.get()
    engine = settings.get("image_engine", "gallery")
    cf_account_id = settings.get("cf_account_id") or os.environ.get("CF_ACCOUNT_ID") or ""
    cf_api_token = settings.get("cf_api_token") or os.environ.get("CF_API_TOKEN") or ""

    enhanced_prompt = prompt
    if "masterpiece" not in enhanced_prompt.lower() and "best quality" not in enhanced_prompt.lower():
        enhanced_prompt += ", masterpiece, best quality, ultra-detailed, cinematic lighting, sharp focus"

    negative_prompt = (
        "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, "
        "fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, "
        "signature, watermark, username, blurry, mutation, deformed, ugly, extra limbs"
    )

    encoded_prompt = urllib.parse.quote_plus(enhanced_prompt)
    pollinations_url = (
        f"https://image.pollinations.ai/prompt/{encoded_prompt}"
        f"?width={width}&height={height}&nologo=true&enhance=true"
    )

    stock_images = _list_stock_images()
    use_stock = engine == "gallery" or (
        engine == "gallery-hybrid" and (int(hashlib.sha256(prompt.encode()).hexdigest()[:2], 16) < 204)
    )
    # gallery-hybrid: ハッシュ上位8bit < 204 ≈ 80%

    if use_stock and stock_images:
        selected = _select_stock_image(prompt, stock_images)
        if selected is not None:
            try:
                img_bytes = selected.read_bytes()
                suffix = selected.suffix.lower()
                media_type = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".webp": "image/webp",
                }.get(suffix, "image/png")
                theme = _theme_of_file(selected) or "any"
                logger.info(
                    f"[ImageGen] 📸 stock theme={theme} file={selected.name} "
                    f"(detected={_detect_theme(prompt) or 'none'})"
                )
                return Response(
                    content=img_bytes,
                    media_type=media_type,
                    headers={
                        "Cache-Control": "public, max-age=86400",
                        "X-Stock-File": selected.name,
                        "X-Stock-Theme": theme,
                    },
                )
            except Exception as e:
                logger.warning(f"[ImageGen] ストック読み込み失敗: {e}")

    if engine == "gallery" and not stock_images:
        logger.warning("[ImageGen] gallery モードだがストック画像が0件です。フォールバックします。")

    if engine in CF_MODELS and cf_api_token and cf_account_id:
        model_id = CF_MODELS[engine]
        url = f"https://api.cloudflare.com/client/v4/accounts/{cf_account_id}/ai/run/{model_id}"
        headers = {
            "Authorization": f"Bearer {cf_api_token}",
            "Content-Type": "application/json",
        }
        if engine == "cf-sdxl":
            payload = {
                "prompt": enhanced_prompt,
                "negative_prompt": negative_prompt,
                "num_steps": 8,
                "width": width,
                "height": height,
            }
        else:
            payload = {"prompt": enhanced_prompt, "num_steps": 8}

        try:
            logger.info(
                f"[ImageGen] Cloudflare ({engine}: {model_id}) "
                f"prompt='{prompt[:50]}...'"
            )
            async with httpx.AsyncClient(timeout=45.0) as client:
                res = await client.post(url, headers=headers, json=payload)
                if res.status_code == 200 and len(res.content) > 1000:
                    content_type = res.headers.get("content-type", "image/png")
                    if "image" in content_type or res.content[:4] in (
                        b"\x89PNG",
                        b"\xff\xd8\xff\xe0",
                        b"\xff\xd8\xff\xe1",
                    ):
                        return Response(content=res.content, media_type=content_type)
                    logger.warning(f"[ImageGen] CF非画像レスポンス: {res.text[:200]}")
                else:
                    logger.warning(
                        f"[ImageGen] CFエラー status={res.status_code}: {res.text[:200]}"
                    )
        except Exception as e:
            logger.error(f"[ImageGen] CF通信例外: {e}")

        logger.info("[ImageGen] Cloudflare失敗 → Pollinations フォールバック")

    return RedirectResponse(url=pollinations_url, status_code=307)
