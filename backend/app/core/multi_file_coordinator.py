"""
Multi-File Coordinator — 複数ファイルの一貫変更を調整する

【CLINE級機能】
- SEARCHブロック事前検証＋自動修復（fuzzy_replace連携）
- ファイル変更検出によるキャッシュ無効化
- 依存グラフベースの実行順序最適化
"""
import re
from typing import Optional
from pathlib import Path
from app.core.tools.handler import ToolHandler
from app.core.sandbox import git_snapshot
from app.routers.workspace import get_workspace_dir
from app.utils.logger import get_logger

logger = get_logger(__name__)


def parse_multi_file_plan(supervisor_json: dict) -> Optional[dict]:
    """
    SupervisorのJSONからマルチファイルプランを抽出。
    """
    if not isinstance(supervisor_json, dict):
        return None
    
    plan = supervisor_json.get("multi_file_plan") or supervisor_json.get("plan")
    if not plan or not isinstance(plan, dict):
        return None
    
    files = plan.get("files", [])
    if not files:
        return None
    
    normalized_files = []
    for i, f in enumerate(files):
        if isinstance(f, str):
            normalized_files.append({"path": f, "type": "create", "depends_on": [], "content": ""})
        elif isinstance(f, dict):
            normalized_files.append({
                "path": f.get("path", f"unknown_{i}"),
                "type": f.get("type", "create"),
                "content": f.get("content", ""),
                "depends_on": f.get("depends_on", []),
                "description": f.get("description", ""),
            })
    
    return {
        "files": normalized_files,
        "execution_order": plan.get("execution_order", [f["path"] for f in normalized_files]),
        "rollback_strategy": plan.get("rollback_strategy", "best_effort"),
        "verification": plan.get("verification", {}),
    }


def build_dependency_graph(files: list) -> tuple[dict, list]:
    """依存グラフを構築し、トポロジカルソート順を返す。"""
    graph = {}
    path_set = {f["path"] for f in files}
    for f in files:
        path = f["path"]
        graph[path] = {"depends_on": [], "depended_by": [], "info": f}
        for dep in f.get("depends_on", []):
            if dep in path_set:
                graph[path]["depends_on"].append(dep)
                graph[dep]["depended_by"].append(path)
    
    in_degree = {p: len(g["depends_on"]) for p, g in graph.items()}
    queue = [p for p, d in in_degree.items() if d == 0]
    order = []
    while queue:
        node = queue.pop(0)
        order.append(node)
        for d in graph[node]["depended_by"]:
            in_degree[d] -= 1
            if in_degree[d] == 0:
                queue.append(d)
    if len(order) != len(graph):
        logger.warning("循環依存を検出。依存関係を無視。")
        order = list(graph.keys())
    return graph, order


def _validate_and_auto_fix(file_path: str, content: str) -> Optional[tuple[str, str]]:
    """
    SEARCHブロックを検証し、不一致なら自動修復。
    Returns: (メッセージ, 修正後content) または None（失敗）
    """
    full_path = get_workspace_dir() / file_path
    if not full_path.exists():
        return None  # 新規ファイル
    
    try:
        file_content = full_path.read_text(encoding='utf-8')
    except Exception:
        return None
    
    search_m = re.search(r'<search>\n?(.*?)\n?</search>', content, re.DOTALL)
    replace_m = re.search(r'<replace_with>\n?(.*?)\n?</replace_with>', content, re.DOTALL)
    if not search_m:
        return None
    
    search_text = search_m.group(1)
    replace_text = replace_m.group(1) if replace_m else ""
    
    # Step1: 完全一致
    if search_text in file_content:
        return ("完全一致", content)
    
    # Step2: 空白正規化
    from app.core.file_edit_fallback import _normalize_whitespace
    norm_file = _normalize_whitespace(file_content)
    norm_search = _normalize_whitespace(search_text)
    if norm_search in norm_file:
        idx = norm_file.find(norm_search)
        file_lines = file_content.split('\n')
        norm_lines = norm_file.split('\n')
        search_lines = norm_search.split('\n')
        prefix = '\n'.join(norm_lines)[:idx]
        start_line = prefix.count('\n')
        actual_search = '\n'.join(file_lines[start_line:start_line + len(search_lines)])
        new_content = content.replace(search_text, actual_search, 1)
        return ("[自動修復] 空白差異を正規化", new_content)
    
    # Step3: 句読点正規化
    from app.core.file_edit_fallback import _normalize_japanese_punctuation
    if _normalize_japanese_punctuation(norm_search) in _normalize_japanese_punctuation(norm_file):
        return ("[自動修復] 句読点差異を正規化", content)
    
    # Step4: 範囲マッチ
    s_lines = search_text.split('\n')
    f_lines = file_content.split('\n')
    first = s_lines[0].strip()
    last = s_lines[-1].strip()
    if first and last:
        for i in range(len(f_lines)):
            if f_lines[i].strip() == first:
                for j in range(i, min(i + len(s_lines) + 10, len(f_lines))):
                    if j < len(f_lines) and f_lines[j].strip() == last:
                        actual_search = '\n'.join(f_lines[i:j+1])
                        new_content = content.replace(search_text, actual_search, 1)
                        return ("[自動修復] 範囲マッチで位置特定", new_content)
    
    return None


async def execute_multi_file_plan(
    plan: dict, session_id: str, mode: str, allow_mocks: bool = False,
) -> list[dict]:
    """マルチファイルプランを実行（SEARCH事前検証＋自動修復付き）。"""
    files = plan["files"]
    rollback_strategy = plan.get("rollback_strategy", "best_effort")
    
    _, sorted_order = build_dependency_graph(files)
    path_to_file = {f["path"]: f for f in files}
    ordered = []
    for p in sorted_order:
        if p in path_to_file:
            ordered.append(path_to_file[p])
    for f in files:
        if f not in ordered:
            ordered.append(f)
    
    results = []
    rollback_files = []
    
    if mode == "task":
        git_snapshot(str(get_workspace_dir()), "snapshot")
    
    for finfo in ordered:
        path = finfo.get("path", "unknown")
        content = finfo.get("content", "")
        ftype = finfo.get("type", "create")
        
        if not content:
            results.append({"path": path, "success": True, "skipped": True})
            continue
        
        # 自動修復
        if ftype == "update":
            fix = _validate_and_auto_fix(path, content)
            if fix:
                msg, fixed = fix
                if msg != "完全一致":
                    logger.info(f"✅ {msg}: {path}")
                    content = fixed
            else:
                fp = get_workspace_dir() / path
                fc = fp.read_text(encoding='utf-8') if fp.exists() else ""
                err = (
                    f"⚠️ **[SEARCHブロック不一致]** 自動修復失敗。\n"
                    f"ファイル最新内容:\n```\n{fc[:2000]}```\n"
                    f"SEARCHを修正して再試行。"
                )
                results.append({"path": path, "success": False, "error": err})
                rollback_files.append(path)
                if rollback_strategy == "all_or_nothing":
                    break
                continue
        
        # contentが既にXMLタグを含むか
        if "<search>" in content or "<file " in content:
            xml_tag = content
        elif ftype == "update":
            xml_tag = f'<replace path="{path}">\n<search>\n{content}\n</search>\n<replace_with>\n{content}\n</replace_with>\n</replace>'
        else:
            xml_tag = f'<file path="{path}">\n{content}\n</file>'
        
        handler = ToolHandler(session_id=session_id, mode=mode, allow_mocks=allow_mocks)
        try:
            await handler.execute_tools(xml_tag)
            has_err = any("エラー" in r or "Error" in r for r in handler.tool_results) if handler.tool_results else False
            results.append({
                "path": path, "success": not has_err,
                "error": "\n".join(handler.tool_results) if has_err else None,
            })
            if not has_err:
                logger.info(f"✅ {path}")
            else:
                logger.error(f"❌ {path}")
                rollback_files.append(path)
                if rollback_strategy == "all_or_nothing":
                    break
        except Exception as e:
            logger.error(f"❌ {path}: {e}")
            results.append({"path": path, "success": False, "error": str(e)})
            rollback_files.append(path)
            if rollback_strategy == "all_or_nothing":
                break
    
    # Verification
    verification = plan.get("verification", {})
    if verification and all(r.get("success") for r in results if not r.get("skipped")):
        cmd = verification.get("command", "")
        if cmd:
            h = ToolHandler(session_id=session_id, mode=mode, allow_mocks=allow_mocks)
            await h.execute_tools(f"<run_command>{cmd}</run_command>")
            if h.tool_results:
                tr = "\n".join(h.tool_results)
                results.append({
                    "path": "verification",
                    "success": "失敗" not in tr and "Error" not in tr,
                    "output": tr,
                })
    
    return results


def coordinate_after_writes(paths: list[str]) -> dict:
    """
    Host-side multi-file write post-step (wired from ToolHandler).
    Records activity and returns a small summary for the agent loop.
    """
    unique = []
    seen = set()
    for p in paths or []:
        if not p or p in seen:
            continue
        seen.add(p)
        unique.append(p.replace("\\", "/"))

    if not unique:
        return {"ok": True, "paths": [], "message": "no paths"}

    try:
        from app.core.workspace_state import record_activity
        record_activity("multi_file_write", f"{len(unique)} files: {', '.join(unique[:8])}")
    except Exception:
        pass

    logger.info(f"📎 multi_file_coordinator: {len(unique)} paths written")
    return {
        "ok": True,
        "paths": unique,
        "message": f"Coordinated {len(unique)} file write(s)",
        "hint": (
            "複数ファイル変更後はワークスペースルートでビルド検証し、"
            "Acceptance 未達項目があれば先に埋めること。"
        ),
    }