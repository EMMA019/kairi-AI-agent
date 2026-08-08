"""
Codebase Search — コードベース横断検索ツール

Executorが <search_codebase query="..." /> を出力すると、
ripgrep (rg) または grep -rn を使ってプロジェクト全体を横断検索。

【従来の問題】
- AIがファイル内容を把握するには毎回 <read_file> が必要で非効率
- どのファイルに何があるか全貌を掴めない

【解決】
- ripgrep で一発検索 → ファイル名:行番号:内容 を返す
- 結果を Executor が読んで状況把握
"""
import re
import subprocess
from pathlib import Path
from typing import Optional
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 検索対象外のディレクトリ
IGNORE_DIRS = [
    "node_modules", ".git", "__pycache__", "venv", ".venv",
    "dist", "build", ".next", ".nuxt", "coverage",
    ".vscode", "idea", "*.egg-info", ".tox",
    "cache", "storage", "data", "output",
]

# 検索対象のファイル拡張子
TARGET_EXTENSIONS = [
    ".py", ".js", ".ts", ".tsx", ".jsx", ".vue", ".svelte",
    ".go", ".rs", ".java", ".kt", ".swift",
    ".css", ".scss", ".less", ".html",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".md", ".txt", ".rst",
    ".sh", ".bash", ".zsh", ".ps1",
    ".sql", ".graphql", ".proto",
    ".c", ".cpp", ".h", ".hpp",
]


async def search_codebase(
    query: str,
    workspace_dir: str,
    max_results: int = 20,
) -> str:
    """
    コードベースを横断検索し、結果を文字列で返す。
    
    Args:
        query: 検索クエリ（正規表現 or プレーンテキスト）
        workspace_dir: 検索対象のワークスペースディレクトリ
        max_results: 最大結果件数
    
    Returns:
        検索結果の整形文字列
    """
    work_path = Path(workspace_dir)
    if not work_path.exists():
        return f"[エラー: ワークスペースが見つかりません: {workspace_dir}]"
    
    # Step 1: ripgrep があれば使用（最速）
    has_rg = _check_command("rg")
    if has_rg:
        return await _search_with_rg(query, str(work_path), max_results)
    
    # Step 2: fallback に grep -rn を使用
    has_grep = _check_command("grep")
    if has_grep:
        return await _search_with_grep(query, str(work_path), max_results)
    
    # Step 3: fallback に Python の glob + ファイル読み込み
    return await _search_with_python(query, str(work_path), max_results)


def _check_command(cmd: str) -> bool:
    """コマンドが使用可能かチェック"""
    try:
        subprocess.run(
            [cmd, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


async def _search_with_rg(query: str, workspace: str, max_results: int) -> str:
    """ripgrep で検索"""
    try:
        # ディレクトリ除外オプション
        ignore_args = []
        for d in IGNORE_DIRS:
            ignore_args.extend(["--glob", f"!{d}/**"])
        
        result = subprocess.run(
            ["rg", "-n", "--no-heading", "--max-count", str(max_results),
             "-i", query, workspace] + ignore_args,
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        if result.returncode == 0 and result.stdout:
            lines = result.stdout.strip().split("\n")[:max_results]
            formatted = f"🔍 コードベース検索結果: '{query}' ({len(lines)}件)\n\n"
            
            for line in lines:
                # ripgrep 出力形式: ファイルパス:行番号:内容
                parts = line.split(":", 2)
                if len(parts) == 3:
                    file_path, line_num, content = parts
                    # ワークスペースパスを相対パスに
                    if workspace in file_path:
                        file_path = file_path.replace(workspace, "").lstrip("/\\")
                    formatted += f"📄 {file_path}:{line_num}\n  {content.strip()[:200]}\n\n"
                else:
                    formatted += f"  {line}\n"
            
            return formatted
        else:
            return f"🔍 コードベース検索: '{query}' に一致する結果は見つかりませんでした。"
            
    except subprocess.TimeoutExpired:
        return "[エラー: 検索が30秒でタイムアウトしました]"
    except Exception as e:
        return f"[エラー: 検索実行失敗: {e}]"


async def _search_with_grep(query: str, workspace: str, max_results: int) -> str:
    """grep -rn で検索（ripgrepがない場合のフォールバック）"""
    try:
        # 対象外ディレクトリを除外
        exclude_args = []
        for d in IGNORE_DIRS:
            exclude_args.extend(["--exclude-dir", d])
        
        result = subprocess.run(
            ["grep", "-rn", "--max-count", str(max_results),
             "-i", query, workspace] + exclude_args,
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        if result.returncode == 0 and result.stdout:
            lines = result.stdout.strip().split("\n")[:max_results]
            formatted = f"🔍 コードベース検索結果: '{query}' ({len(lines)}件)\n\n"
            
            for line in lines:
                parts = line.split(":", 2)
                if len(parts) == 3:
                    file_path, line_num, content = parts
                    if workspace in file_path:
                        file_path = file_path.replace(workspace, "").lstrip("/\\")
                    formatted += f"📄 {file_path}:{line_num}\n  {content.strip()[:200]}\n\n"
                else:
                    formatted += f"  {line}\n"
            
            return formatted
        else:
            return f"🔍 コードベース検索: '{query}' に一致する結果は見つかりませんでした。"
            
    except subprocess.TimeoutExpired:
        return "[エラー: 検索が30秒でタイムアウトしました]"
    except Exception as e:
        return f"[エラー: 検索実行失敗: {e}]"


async def _search_with_python(query: str, workspace: str, max_results: int) -> str:
    """Pythonのglob+ファイル読み込み（最終フォールバック）"""
    try:
        import os
        import fnmatch
        
        results = []
        query_lower = query.lower()
        
        for root, dirs, files in os.walk(workspace):
            # 除外ディレクトリをスキップ
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]
            
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext not in TARGET_EXTENSIONS:
                    continue
                
                file_path = os.path.join(root, file)
                
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        for line_num, line_content in enumerate(f, 1):
                            if query_lower in line_content.lower():
                                rel_path = os.path.relpath(file_path, workspace)
                                results.append(
                                    f"📄 {rel_path}:{line_num}\n  {line_content.strip()[:200]}"
                                )
                                if len(results) >= max_results:
                                    break
                except Exception:
                    continue
                
                if len(results) >= max_results:
                    break
        
        if results:
            formatted = f"🔍 コードベース検索結果: '{query}' ({len(results)}件)\n\n"
            formatted += "\n\n".join(results)
            return formatted
        else:
            return f"🔍 コードベース検索: '{query}' に一致する結果は見つかりませんでした。"
            
    except Exception as e:
        return f"[エラー: 検索実行失敗: {e}]"


async def handle_search_codebase_tag(
    current_response: str,
    workspace_dir: str,
) -> tuple[str, list[str]]:
    """
    Executorの応答から <search_codebase> タグを処理。
    
    Returns:
        (更新された応答テキスト, ツール結果のリスト)
    """
    results = []
    
    for match in re.finditer(r'<search_codebase\s+query=([\'"])(.*?)\1\s*/>', current_response):
        query = match.group(2).strip()
        if not query:
            continue
        
        logger.info(f"🔍 コードベース検索を実行: {query}")
        search_result = await search_codebase(query, workspace_dir)
        results.append(f"【コードベース検索結果: {query}】\n{search_result}")
        
        replacement = f"\n\n*[🔍 コードベース検索結果: {query}]*\n\n"
        current_response = current_response.replace(match.group(0), replacement)
    
    return current_response, results