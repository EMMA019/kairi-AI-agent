"""
プロジェクトコンテキスト自動収集モジュール (Claude Code準拠)。
タスクモード（コーディング・リファクタリング）開始時に、対象ワークスペースの
ディレクトリ構造、プロジェクトタイプ、依存関係、最近の変更履歴を自動スキャンし、
Executor / Supervisor の初回プロンプトに自動注入する。
"""
import os
import subprocess
from pathlib import Path
from typing import Optional
from app.utils.logger import get_logger

logger = get_logger(__name__)

IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", "venv", ".venv", "env", ".env",
    "dist", "build", ".next", ".nuxt", "coverage", ".pytest_cache", ".mypy_cache",
    "target", "vendor", ".bundle", "tmp", "temp", "storage", "cache", "logs"
}


def generate_tree(workspace_dir: str, max_depth: int = 3, max_entries: int = 60) -> str:
    """指定ディレクトリのツリー構造（階層・ファイルタイプ付き）を生成"""
    base_path = Path(workspace_dir)
    if not base_path.exists() or not base_path.is_dir():
        return "[ワークスペースディレクトリが見つかりません]"

    lines = []
    entries_count = 0

    def _walk(dir_path: Path, prefix: str, depth: int):
        nonlocal entries_count
        if depth > max_depth or entries_count >= max_entries:
            if entries_count == max_entries:
                lines.append(f"{prefix}... [エントリ数が {max_entries} を超えたため省略]")
                entries_count += 1
            return

        try:
            items = sorted(os.scandir(dir_path), key=lambda e: (not e.is_dir(), e.name.lower()))
        except Exception:
            return

        for i, entry in enumerate(items):
            if entry.name.startswith(".") or entry.name in IGNORE_DIRS:
                continue
                
            is_last = (i == len(items) - 1)
            connector = "└── " if is_last else "├── "
            new_prefix = prefix + ("    " if is_last else "│   ")
            
            entries_count += 1
            if entries_count > max_entries:
                lines.append(f"{prefix}... [省略]")
                break

            if entry.is_dir():
                try:
                    child_count = len([c for c in os.scandir(entry.path) if not c.name.startswith(".") and c.name not in IGNORE_DIRS])
                except Exception:
                    child_count = "?"
                lines.append(f"{prefix}{connector}📁 {entry.name}/ ({child_count} items)")
                _walk(Path(entry.path), new_prefix, depth + 1)
            else:
                try:
                    size = entry.stat().st_size
                    if size < 1024:
                        size_str = f"{size}B"
                    elif size < 1024 * 1024:
                        size_str = f"{size/1024:.1f}KB"
                    else:
                        size_str = f"{size/(1024*1024):.1f}MB"
                except Exception:
                    size_str = "?B"
                lines.append(f"{prefix}{connector}📄 {entry.name} ({size_str})")

    lines.append(f"📁 {base_path.name}/ (Workspace Root)")
    _walk(base_path, "", 1)
    return "\n".join(lines)


def detect_project_type(workspace_dir: str) -> str:
    """プロジェクト設定ファイル群から技術スタックを自動判定"""
    base = Path(workspace_dir)
    types = []
    
    if (base / "package.json").exists():
        if (base / "next.config.js").exists() or (base / "next.config.mjs").exists() or (base / "next.config.ts").exists():
            types.append("TypeScript / React (Next.js)")
        elif (base / "vite.config.ts").exists() or (base / "vite.config.js").exists():
            types.append("TypeScript / React or Vue (Vite)")
        elif (base / "tsconfig.json").exists():
            types.append("Node.js / TypeScript")
        else:
            types.append("Node.js / JavaScript")
            
    if (base / "pyproject.toml").exists() or (base / "requirements.txt").exists() or (base / "setup.py").exists():
        if (base / "fastapi").exists() or (base / "app" / "main.py").exists():
            types.append("Python (FastAPI / Web API)")
        elif (base / "manage.py").exists():
            types.append("Python (Django)")
        else:
            types.append("Python")
            
    if (base / "Cargo.toml").exists():
        types.append("Rust")
    if (base / "go.mod").exists():
        types.append("Go")
    if (base / "pom.xml").exists() or (base / "build.gradle").exists():
        types.append("Java / Kotlin")
    if (base / "Dockerfile").exists() or (base / "docker-compose.yml").exists() or (base / "compose.yaml").exists():
        types.append("Docker Containerized")
        
    if not types:
        return "汎用プロジェクト（言語指定なし）"
    return " + ".join(types)


def read_key_configs(workspace_dir: str, max_chars: int = 1200) -> str:
    """主要な設定ファイルや依存関係（package.json, pyproject.toml等）の要点を抽出"""
    base = Path(workspace_dir)
    summaries = []
    
    # 1. package.json
    pkg_json = base / "package.json"
    if pkg_json.exists():
        try:
            import json
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            deps = list(data.get("dependencies", {}).keys())[:15]
            dev_deps = list(data.get("devDependencies", {}).keys())[:10]
            scripts = list(data.get("scripts", {}).keys())[:8]
            info = f"- [package.json] Scripts: {', '.join(scripts)}\n  Dependencies: {', '.join(deps)}"
            if dev_deps:
                info += f"\n  DevDependencies: {', '.join(dev_deps)}"
            summaries.append(info)
        except Exception as e:
            summaries.append(f"- [package.json] 読み込み失敗: {e}")
            
    # 2. pyproject.toml / requirements.txt
    pyproject = base / "pyproject.toml"
    if pyproject.exists():
        try:
            text = pyproject.read_text(encoding="utf-8")
            lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
            summaries.append(f"- [pyproject.toml] 先頭設定:\n  " + "\n  ".join(lines[:12]))
        except Exception:
            pass
    elif (base / "requirements.txt").exists():
        try:
            text = (base / "requirements.txt").read_text(encoding="utf-8")
            deps = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")][:15]
            summaries.append(f"- [requirements.txt]: {', '.join(deps)}")
        except Exception:
            pass
            
    # 3. Dockerfile
    dockerfile = base / "Dockerfile"
    if dockerfile.exists():
        try:
            text = dockerfile.read_text(encoding="utf-8")
            lines = [l.strip() for l in text.splitlines() if l.strip().lower().startswith(("from", "workdir", "cmd", "entrypoint", "copy", "run"))][:6]
            summaries.append(f"- [Dockerfile]: " + " / ".join(lines))
        except Exception:
            pass
            
    if not summaries:
        return "（主要な構成ファイルは見つかりませんでした）"
        
    res = "\n".join(summaries)
    if len(res) > max_chars:
        res = res[:max_chars] + "... [中略]"
    return res


def get_recent_changes(workspace_dir: str) -> str:
    """Gitリポジトリであれば直近の変更履歴やステータスを取得"""
    try:
        if not (Path(workspace_dir) / ".git").exists():
            return "（Gitリポジトリではありません）"
            
        status_out = subprocess.check_output(
            ["git", "status", "--short"],
            cwd=workspace_dir,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=3
        ).strip()
        
        log_out = subprocess.check_output(
            ["git", "log", "-n", "3", "--oneline"],
            cwd=workspace_dir,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=3
        ).strip()
        
        res_parts = []
        if status_out:
            res_parts.append(f"【現在のGit未コミット変更】\n{status_out[:400]}")
        if log_out:
            res_parts.append(f"【直近3件のコミット】\n{log_out}")
            
        return "\n\n".join(res_parts) if res_parts else "（変更履歴なし）"
    except Exception:
        return "（Git情報の取得に失敗またはタイムアウトしました）"


async def gather_project_context(workspace_dir: str) -> str:
    """
    タスクモード開始時に自動実行するプロジェクトスキャナー。
    ディレクトリ構造、言語、依存関係、Git状況を1つのコンテキスト文字列に統合する。
    """
    try:
        tree_str = generate_tree(workspace_dir, max_depth=3, max_entries=50)
        proj_type = detect_project_type(workspace_dir)
        configs_str = read_key_configs(workspace_dir)
        git_str = get_recent_changes(workspace_dir)
        
        context_text = (
            f"【🤖 プロジェクトコンテキスト自動検出 (Claude Code準拠)】\n"
            f"**プロジェクトタイプ**: {proj_type}\n\n"
            f"**ディレクトリ構造 (最大3階層)**:\n```\n{tree_str}\n```\n\n"
            f"**依存関係・主要構成**:\n{configs_str}\n\n"
            f"**変更履歴・ステータス**:\n{git_str}"
        )
        logger.info(f"📁 プロジェクトコンテキスト自動収集完了 ({len(context_text)}文字)")
        return context_text
    except Exception as e:
        logger.warning(f"プロジェクトコンテキスト収集エラー: {e}")
        return ""
