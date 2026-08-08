from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
from pathlib import Path
from typing import List, Optional
from fastapi.responses import StreamingResponse
import io
import zipfile
from app.utils.logger import get_logger
from app.core.workspace_state import (
    clear_all_changes,
    list_activity,
    list_changes,
    pop_change,
    record_activity,
)
from app.core.project_context import detect_project_type

logger = get_logger(__name__)

router = APIRouter()

_REPO_ROOT = Path(__file__).resolve().parents[3]
ROOT_OUTPUT_DIR = _REPO_ROOT / "output"
ROOT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

_STORAGE_DIR = Path(__file__).resolve().parents[2] / "storage"
_WORKSPACE_ROOT_FILE = _STORAGE_DIR / "workspace_root.txt"

BASE_WORKSPACE_DIR = ROOT_OUTPUT_DIR
_ACTIVE_WORKSPACE = str(BASE_WORKSPACE_DIR)

_BLOCKED_PREFIXES = (
    Path("C:/Windows"),
    Path("C:/Program Files"),
    Path("C:/Program Files (x86)"),
    Path("/etc"),
    Path("/usr"),
    Path("/bin"),
    Path("/sbin"),
    Path("/dev"),
    Path("/proc"),
    Path("/sys"),
)


def _load_persisted_workspace() -> Optional[str]:
    try:
        if _WORKSPACE_ROOT_FILE.exists():
            raw = _WORKSPACE_ROOT_FILE.read_text(encoding="utf-8").strip()
            if raw:
                p = Path(raw).expanduser().resolve()
                if p.is_dir():
                    return str(p)
    except Exception as e:
        logger.warning(f"Failed to load persisted workspace root: {e}")
    return None


def _persist_workspace(path: str) -> None:
    try:
        _STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        _WORKSPACE_ROOT_FILE.write_text(path, encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to persist workspace root: {e}")


def get_workspace_dir() -> Path:
    """現在の動的なワークスペースディレクトリPathを取得"""
    global _ACTIVE_WORKSPACE
    if _ACTIVE_WORKSPACE:
        p = Path(_ACTIVE_WORKSPACE)
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return p
    return ROOT_OUTPUT_DIR


IGNORE_DIRS = {
    "venv", ".venv", "node_modules", ".git", "__pycache__",
    "dist", "build", ".next", ".nuxt", "coverage",
    ".vscode", "idea", "*.egg-info", ".tox",
    "cache", "storage", "data", "output", "uploads",
}

IGNORE_EXTS = {
    ".db", ".sqlite", ".sqlite3", ".pyc", ".pyo", ".png", ".jpg", ".jpeg",
    ".gif", ".ico", ".svg", ".webp", ".exe", ".dll", ".so", ".dylib",
    ".zip", ".tar", ".gz", ".7z", ".rar", ".pdf", ".mp3", ".mp4", ".mov",
}


def set_workspace_path(path: str, persist: bool = False):
    """アクティブなワークスペースパスを設定"""
    global _ACTIVE_WORKSPACE, BASE_WORKSPACE_DIR
    resolved = str(Path(path).expanduser().resolve())
    _ACTIVE_WORKSPACE = resolved
    BASE_WORKSPACE_DIR = Path(resolved)
    try:
        import app.core.tools.handler as h
        h.BASE_WORKSPACE_DIR = Path(resolved)
    except Exception:
        pass
    if persist:
        _persist_workspace(resolved)
    clear_all_changes()
    record_activity("open", resolved)


def get_current_workspace() -> str:
    """現在のワークスペースパスを取得"""
    return str(get_workspace_dir())


def _validate_open_path(path: str) -> Path:
    raw = (path or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Path is required")
    try:
        p = Path(raw).expanduser().resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not p.exists() or not p.is_dir():
        raise HTTPException(status_code=400, detail="Directory does not exist")
    for blocked in _BLOCKED_PREFIXES:
        try:
            if p == blocked.resolve() or blocked.resolve() in p.parents:
                raise HTTPException(status_code=400, detail="Path is not allowed")
        except HTTPException:
            raise
        except Exception:
            continue
    return p


def _workspace_status() -> dict:
    ws = get_workspace_dir()
    root = str(ws.resolve()) if ws.exists() else str(ws)
    try:
        project_type = detect_project_type(root)
    except Exception:
        project_type = "unknown"
    return {
        "root": root,
        "name": Path(root).name,
        "project_type": project_type,
        "exists": ws.exists(),
    }


# Restore last opened folder on import
_persisted = _load_persisted_workspace()
if _persisted:
    set_workspace_path(_persisted, persist=False)


class FileRequest(BaseModel):
    path: str
    content: str


class SaveRequest(BaseModel):
    files: List[FileRequest]


class OpenWorkspaceRequest(BaseModel):
    path: str


class SaveSpecRequest(BaseModel):
    content: str
    filename: str = "SPEC.md"


class DiscardRequest(BaseModel):
    path: str

@router.post("/workspace/save")
async def save_files(request: SaveRequest):
    """
    指定されたパスにファイルを保存する。
    ディレクトリ・トラバーサルを防ぐため、現在のワークスペース配下のみ許可。
    """
    saved_files = []
    ws_dir = get_workspace_dir()
    
    for file_req in request.files:
        # パスをサニタイズ（上位ディレクトリへの参照を禁止）
        safe_path = file_req.path.replace("..", "").lstrip("/\\")
        target_path = ws_dir / safe_path
        
        # 保存先ディレクトリを作成
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(file_req.content)
            saved_files.append(str(target_path))
            logger.info(f"ファイルを保存しました: {target_path}")
        except Exception as e:
            logger.error(f"ファイル保存エラー ({target_path}): {e}")
            raise HTTPException(status_code=500, detail=f"ファイル保存に失敗しました: {safe_path}")
            
    return {"success": True, "saved_files": saved_files, "base_dir": str(ws_dir)}

def get_workspace_files_text() -> str:
    """現在のワークスペース内の全テキストファイルを <file> タグでラップして返す（キャッシュ効率・高速化対応）"""
    ws_dir = get_workspace_dir()
    if not ws_dir.exists():
        return "ワークスペースは空です。"
    
    context = ""
    total_chars = 0
    max_total_chars = 100_000  # 最大100KBに制限してキャッシュ・通信効率を最大化
    max_file_chars = 50_000    # 1ファイルあたり最大50KB
    file_count = 0
    max_files = 30
    
    for root, dirs, files in os.walk(ws_dir):
        # 除外ディレクトリをスキップ
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]
        
        for file in sorted(files):
            if file.startswith(".") or file == "__pycache__":
                continue
            ext = os.path.splitext(file)[1].lower()
            if ext in IGNORE_EXTS:
                continue
                
            file_path = Path(root) / file
            rel_path = file_path.relative_to(ws_dir).as_posix()
            
            try:
                if file_path.stat().st_size > 1_000_000:
                    context += f'<file path="{rel_path}">\n[サイズ超過ファイル ({file_path.stat().st_size} bytes): <read_file> で確認してください]\n</file>\n'
                    continue
                    
                content = file_path.read_text(encoding="utf-8")
                if len(content) > max_file_chars:
                    content = content[:max_file_chars] + f"\n... [{len(content) - max_file_chars}文字省略: 必要に応じて <read_file> で確認してください] ..."
                    
                if total_chars + len(content) > max_total_chars or file_count >= max_files:
                    context += f'<file path="{rel_path}">\n[ファイル上限・サイズ上限に到達: 必要に応じて <read_file> または <search_codebase> を使用してください]\n</file>\n'
                    continue
                    
                context += f'<file path="{rel_path}">\n{content}\n</file>\n'
                total_chars += len(content)
                file_count += 1
            except Exception:
                pass
    return context.strip() if context else "ワークスペースは空です。"

@router.get("/workspace/tree")
async def get_workspace_tree():
    """ワークスペース内のファイルツリーを返す"""
    ws_dir = get_workspace_dir()
    if not ws_dir.exists():
        return []
        
    def build_tree(dir_path: Path):
        tree = []
        for item in sorted(dir_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if item.name.startswith(".") or item.name in IGNORE_DIRS:
                continue
            if not item.is_dir() and item.suffix.lower() in IGNORE_EXTS:
                continue
                
            node = {
                "name": item.name,
                "path": str(item.relative_to(ws_dir)).replace("\\", "/"),
                "type": "directory" if item.is_dir() else "file"
            }
            if item.is_dir():
                node["children"] = build_tree(item)
            tree.append(node)
        return tree
        
    return build_tree(ws_dir)

@router.get("/workspace/file")
async def get_workspace_file(path: str):
    """ファイルの内容を返す"""
    ws_dir = get_workspace_dir()
    safe_path = path.replace("..", "").lstrip("/\\")
    target = ws_dir / safe_path
    
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
        
    try:
        content = target.read_text(encoding="utf-8")
        return {"content": content}
    except Exception as e:
        logger.error(f"Error reading file {path}: {e}")
        raise HTTPException(status_code=400, detail="Could not read file")

@router.get("/workspace/download")
async def download_workspace():
    """ワークスペース全体を .zip ファイルとしてダウンロードする"""
    ws_dir = get_workspace_dir()
    if not ws_dir.exists():
        raise HTTPException(status_code=404, detail="Workspace is empty")
        
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(ws_dir):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]
            for file in files:
                if file.startswith(".") or file == "__pycache__":
                    continue
                ext = os.path.splitext(file)[1].lower()
                if ext in IGNORE_EXTS:
                    continue
                file_path = Path(root) / file
                rel_path = file_path.relative_to(ws_dir).as_posix()
                zf.write(file_path, arcname=str(rel_path))
                
    zip_buffer.seek(0)
    
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=workspace.zip"}
    )


@router.get("/workspace/status")
async def workspace_status():
    """現在のワークスペースルート・プロジェクト種別を返す"""
    return _workspace_status()


@router.post("/workspace/open")
async def open_workspace(request: OpenWorkspaceRequest):
    """フォルダを開いてワークスペースルートにする（永続化あり）"""
    p = _validate_open_path(request.path)
    set_workspace_path(str(p), persist=True)
    logger.info(f"Workspace opened: {p}")
    return {"success": True, **_workspace_status()}


@router.get("/workspace/changes")
async def workspace_changes():
    """AIが書き換えたファイルの差分一覧"""
    return {"changes": list_changes()}


@router.post("/workspace/discard")
async def discard_change(request: DiscardRequest):
    """指定パスの変更を破棄して before 内容に戻す"""
    safe_path = request.path.replace("..", "").lstrip("/\\")
    change = pop_change(safe_path)
    if change is None:
        raise HTTPException(status_code=404, detail="No recorded change for path")
    ws_dir = get_workspace_dir()
    target = ws_dir / safe_path
    try:
        if not change.before:
            if target.exists():
                target.unlink()
            record_activity("discard", safe_path)
            return {"success": True, "path": safe_path, "action": "deleted"}
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(change.before, encoding="utf-8")
        record_activity("discard", safe_path)
        return {"success": True, "path": safe_path, "action": "restored"}
    except Exception as e:
        logger.error(f"Discard failed ({safe_path}): {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workspace/activity")
async def workspace_activity(limit: int = 40):
    """直近のツール/ファイル操作アクティビティ"""
    return {"activity": list_activity(limit=limit)}


@router.post("/workspace/save-spec")
async def save_spec(request: SaveSpecRequest):
    """ユーザー向け仕様書をワークスペースに SPEC.md として保存"""
    ws_dir = get_workspace_dir()
    name = (request.filename or "SPEC.md").replace("..", "").lstrip("/\\")
    if not name:
        name = "SPEC.md"
    target = ws_dir / name
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(request.content or "", encoding="utf-8")
        record_activity("save_spec", name)
        logger.info(f"Spec saved: {target}")
        return {"success": True, "path": name}
    except Exception as e:
        logger.error(f"Spec save failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workspace/latest-spec")
async def latest_spec(session_id: Optional[str] = None):
    """直近セッションの surface 仕様書（あれば）を返す"""
    if not session_id:
        return {"content": None, "source": None}
    try:
        import json
        from app.core.database import get_db

        async with get_db() as db:
            cursor = await db.execute(
                "SELECT thinking_json, content FROM messages "
                "WHERE session_id = ? AND role = 'assistant' "
                "ORDER BY created_at DESC LIMIT 20",
                (session_id,),
            )
            rows = await cursor.fetchall()
        for row in rows:
            raw = row[0]
            content = row[1]
            if raw:
                try:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                    spec = (parsed or {}).get("spec_document") or {}
                    surface = spec.get("surface")
                    if surface and str(surface).strip():
                        return {"content": surface, "source": "spec_document.surface"}
                except Exception:
                    pass
            if content and ("仕様" in content or "Spec" in content or "# " in str(content)[:80]):
                return {"content": content, "source": "assistant_content"}
    except Exception as e:
        logger.warning(f"latest-spec lookup failed: {e}")
    return {"content": None, "source": None}
