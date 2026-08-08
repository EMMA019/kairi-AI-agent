"""One-click backup: chats + settings (secrets masked by default)."""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.core.app_version import APP_VERSION
from app.routers.settings import SETTINGS_PATH, _SECRET_SETTING_KEYS, app_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

_STORAGE = Path(__file__).resolve().parents[2] / "storage"
_DB_PATH = _STORAGE / "conversations.db"


@router.get("/export")
async def export_backup(include_secrets: bool = Query(False)):
    """
    会話DB + 設定を zip で返す。
    既定では API キー等をマスク。include_secrets=true で生キーも入れる（ユーザー責任）。
    """
    buf = io.BytesIO()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "VERSION.txt",
            f"Kairi {APP_VERSION}\nexported_at={stamp}\ninclude_secrets={include_secrets}\n",
        )
        settings = app_settings.get()
        export_settings = dict(settings)
        if not include_secrets:
            for k in _SECRET_SETTING_KEYS:
                if str(export_settings.get(k) or "").strip():
                    export_settings[k] = "********"
        zf.writestr(
            "settings.json",
            json.dumps(export_settings, ensure_ascii=False, indent=2),
        )
        if _DB_PATH.exists():
            zf.write(_DB_PATH, arcname="conversations.db")
        for name in ("workspace_root.txt",):
            p = _STORAGE / name
            if p.exists():
                zf.write(p, arcname=name)
        # small README inside zip
        zf.writestr(
            "README.txt",
            "Kairi backup\n"
            "- settings.json: app settings (keys masked unless include_secrets)\n"
            "- conversations.db: chat history\n"
            "Restore: stop Kairi, copy files into backend/storage/, restart.\n",
        )

    buf.seek(0)
    filename = f"kairi-backup-{stamp}.zip"
    logger.info(f"Export backup created (include_secrets={include_secrets})")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
