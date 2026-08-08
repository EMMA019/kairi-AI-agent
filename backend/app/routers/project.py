"""
プロジェクト管理APIルーター

プロジェクト = ワークスペースディレクトリ + 会話履歴のコンテナ。
プロジェクトを作成すると `output/{project_name}/` ディレクトリが作成される。
"""
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.core.sandbox import git_snapshot
from app.routers.workspace import ROOT_OUTPUT_DIR
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# プロジェクト情報を保存するJSONファイル
PROJECTS_DB_PATH = Path(__file__).parent.parent.parent / "storage" / "projects.json"
_ACTIVE_PROJECT: str | None = None


class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ProjectInfo(BaseModel):
    id: str
    name: str
    description: str
    path: str
    created_at: str
    updated_at: str
    file_count: int


def _load_projects() -> list[dict]:
    """プロジェクト一覧をJSONから読み込み"""
    if not PROJECTS_DB_PATH.exists():
        # デフォルトプロジェクトを作成
        default = [{
            "id": "main",
            "name": "main",
            "description": "デフォルトプロジェクト",
            "path": str(ROOT_OUTPUT_DIR / "main"),
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }]
        PROJECTS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(PROJECTS_DB_PATH, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=2)
        return default
    
    with open(PROJECTS_DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_projects(projects: list[dict]):
    """プロジェクト一覧をJSONに保存"""
    PROJECTS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PROJECTS_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(projects, f, ensure_ascii=False, indent=2)


def _count_files(project_path: str) -> int:
    """プロジェクト内のファイル数をカウント"""
    path = Path(project_path)
    if not path.exists():
        return 0
    count = 0
    for _ in path.rglob("*"):
        if _.is_file():
            count += 1
    return count


def get_active_project() -> str:
    """現在アクティブなプロジェクトのパスを取得"""
    global _ACTIVE_PROJECT
    if _ACTIVE_PROJECT:
        return _ACTIVE_PROJECT
    
    projects = _load_projects()
    if projects:
        _ACTIVE_PROJECT = projects[0]["id"]
        try:
            from app.routers.workspace import set_workspace_path
            set_workspace_path(projects[0]["path"])
        except Exception:
            pass
        return projects[0]["path"]
    return str(ROOT_OUTPUT_DIR / "main")


def set_active_project(project_id: str) -> str:
    """アクティブプロジェクトを切り替え"""
    global _ACTIVE_PROJECT
    projects = _load_projects()
    for p in projects:
        if p["id"] == project_id:
            _ACTIVE_PROJECT = project_id
            # ワークスペースパスを更新（ToolHandlerのBASE_WORKSPACE_DIRも更新）
            try:
                from app.routers.workspace import set_workspace_path
                set_workspace_path(p["path"])
            except Exception:
                pass
            logger.info(f"🔄 プロジェクト切替: {project_id} -> {p['path']}")
            return p["path"]
    raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")


@router.get("/project")
async def list_projects():
    """全プロジェクト一覧を取得"""
    global _ACTIVE_PROJECT
    projects = _load_projects()
    
    # _ACTIVE_PROJECT が None なら最初のプロジェクトをアクティブに
    if _ACTIVE_PROJECT is None and projects:
        _ACTIVE_PROJECT = projects[0]["id"]
        try:
            from app.routers.workspace import set_workspace_path
            set_workspace_path(projects[0]["path"])
        except Exception:
            pass
    results = []
    for p in projects:
        results.append({
            "id": p["id"],
            "name": p["name"],
            "description": p.get("description", ""),
            "path": p["path"],
            "created_at": p.get("created_at", ""),
            "updated_at": p.get("updated_at", ""),
            "file_count": _count_files(p["path"]),
            "active": p["id"] == _ACTIVE_PROJECT,
        })
    return {"projects": results}


@router.post("/project")
async def create_project(data: ProjectCreate):
    """新規プロジェクトを作成"""
    projects = _load_projects()
    
    # 同名チェック
    if any(p["name"] == data.name for p in projects):
        raise HTTPException(status_code=400, detail=f"Project '{data.name}' already exists")
    
    project_id = data.name.lower().replace(" ", "_").replace("/", "_")
    project_path = ROOT_OUTPUT_DIR / project_id
    
    # ディレクトリ作成
    project_path.mkdir(parents=True, exist_ok=True)
    
    # Git初期化
    git_snapshot(str(project_path), "Project created")
    
    new_project = {
        "id": project_id,
        "name": data.name,
        "description": data.description,
        "path": str(project_path),
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    projects.append(new_project)
    _save_projects(projects)
    
    # 作成したプロジェクトをアクティブに
    set_active_project(project_id)
    
    logger.info(f"📁 プロジェクト作成: {data.name} ({project_path})")
    return {
        "success": True,
        "project": {
            **new_project,
            "file_count": 0,
            "active": True,
        }
    }


@router.post("/project/switch")
async def switch_project(data: dict):
    """アクティブプロジェクトを切り替え"""
    project_id = data.get("project_id", "main")
    path = set_active_project(project_id)
    return {"success": True, "path": path, "project_id": project_id}


@router.delete("/project/{project_id}")
async def delete_project(project_id: str):
    """プロジェクトを削除（ディレクトリは残すオプション）"""
    projects = _load_projects()
    
    if project_id == "main":
        raise HTTPException(status_code=400, detail="Cannot delete main project")
    
    for i, p in enumerate(projects):
        if p["id"] == project_id:
            # ディレクトリ削除（確認済みなら物理削除）
            path = Path(p["path"])
            if path.exists():
                shutil.rmtree(path)
            projects.pop(i)
            _save_projects(projects)
            
            if _ACTIVE_PROJECT == project_id:
                set_active_project("main")
            
            logger.info(f"🗑️ プロジェクト削除: {project_id}")
            return {"success": True}
    
    raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")