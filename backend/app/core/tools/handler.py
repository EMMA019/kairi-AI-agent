import os
import re

import shutil
import datetime
from pathlib import Path

def _create_backup(filepath: str, workspace_dir: str):
    try:
        if not os.path.exists(filepath):
            return
        backup_dir = os.path.join(workspace_dir, ".backup")
        os.makedirs(backup_dir, exist_ok=True)
        filename = os.path.basename(filepath)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"{filename}_{timestamp}.bak")
        shutil.copy2(filepath, backup_path)
        logger.info(f"🛡️ Backup created: {backup_path}")
    except Exception as e:
        logger.warning(f"Failed to create backup for {filepath}: {e}")

import py_compile
import traceback
import logging

from pathlib import Path
from typing import Tuple, List

from app.utils.logger import get_logger
from app.routers.workspace import BASE_WORKSPACE_DIR
from app.core.sandbox import git_snapshot, get_sandbox, normalize_safe_path, safe_read_file, safe_list_dir
from app.core.search.router import fetch_url
from app.core.search import web_search

logger = get_logger(__name__)

MOCK_KEYWORDS = ["TODO", "FIXME", "NotImplemented", "ダミーデータ", "後で実装"]

class ToolHandler:
    """
    実行モデル(Executor)が生成したXMLタグをパースし、
    ファイルの作成・更新、コマンド実行、スクレイピングなどのツール処理を安全に実行する。
    """
    def __init__(self, session_id: str, mode: str, allow_mocks: bool = False):
        self.session_id = session_id
        self.mode = mode
        self.allow_mocks = allow_mocks
        self.tool_results: List[str] = []
        self.escalation_history: List[str] = []
        self.has_escalation: bool = False

    def filter_logs(self, output: str, max_length: int = 2000) -> str:
        """長大なログ出力からエラー箇所や末尾のみを賢く抽出する"""
        if not output or len(output) <= max_length:
            return output
            
        lines = output.splitlines()
        if len(lines) <= 50:
            return output

        import re

        error_pattern = re.compile(r'(error|exception|traceback|err!|fatal|failed)', re.IGNORECASE)
        
        error_indices = [i for i, line in enumerate(lines) if error_pattern.search(line)]
        
        if not error_indices:
            tail_lines = lines[-30:]
            return "[...長大な成功ログのため冒頭を省略...]\n" + "\n".join(tail_lines)
            
        extracted_lines = []
        last_added_idx = -1
        
        if len(error_indices) > 5:
            error_indices = error_indices[-5:]
            
        for idx in error_indices:
            start_idx = max(0, idx - 5)
            end_idx = min(len(lines), idx + 6)
            
            if start_idx > last_added_idx + 1 and last_added_idx != -1:
                extracted_lines.append("\n[...省略...]\n")
                
            for i in range(max(start_idx, last_added_idx + 1), end_idx):
                extracted_lines.append(lines[i])
                last_added_idx = i
                
        if last_added_idx < len(lines) - 1:
            extracted_lines.append("\n[...省略...]\n")
            extracted_lines.extend(lines[-5:])
            
        return "\n".join(extracted_lines)

    def check_mocks(self, content: str) -> str | None:
        """モック実装が含まれているかチェックし、あればエラーメッセージを返す"""
        if self.allow_mocks:
            return None
        found_mocks = [kw for kw in MOCK_KEYWORDS if kw in content]
        if found_mocks:
            return f"モック実装が検出されました ({', '.join(found_mocks)})。TODOやダミーデータを残さず、実際のロジックを完全に実装してください。"
        return None

    def clean_markdown_block(self, content: str) -> str:
        """AIが出力しがちな不要なマークダウンブロックを除去する"""
        clean_content = content.strip()
        if clean_content.startswith("```"):
            clean_content = clean_content.split("\n", 1)[-1] if "\n" in clean_content else ""
        if clean_content.endswith("```"):
            clean_content = clean_content.rsplit("\n", 1)[0] if "\n" in clean_content else ""
        return clean_content.strip()

    def run_linter(self, target_path: Path, is_new_file: bool, original_content: str | None) -> str | None:
        """各種ファイルの構文チェックを行い、エラーならロールバックしてエラーメッセージを返す"""
        error_msg = None
        
        # 1. Pythonの構文チェック
        if target_path.suffix == ".py":
            try:
                py_compile.compile(target_path, doraise=True)
            except py_compile.PyCompileError as pe:
                error_msg = "".join(traceback.format_exception_only(type(pe.exc_value), pe.exc_value))
                
        # 2. JSONの構文チェック
        elif target_path.suffix in [".json"]:
            try:
                import json
                json.loads(target_path.read_text(encoding="utf-8"))
            except Exception as e:
                error_msg = f"JSON Parse Error: {e}"
                
        # 3. TSX/JSX の簡易構文バリデーション
        elif target_path.suffix in [".tsx", ".jsx", ".ts", ".js"]:
            try:
                content = target_path.read_text(encoding="utf-8")
                if "<ReactMarkdown" in content and "</ReactMarkdown>" not in content:
                    error_msg = "Expected corresponding JSX closing tag for 'ReactMarkdown'."
                elif "```" in content and content.count("```") % 2 != 0:
                    error_msg = "Unclosed markdown code fence ``` found in string literal or comment."
            except Exception as e:
                error_msg = str(e)
                
        if error_msg:
            if is_new_file:
                target_path.unlink(missing_ok=True)
            else:
                if original_content is not None:
                    with open(target_path, "w", encoding="utf-8") as f:
                        f.write(original_content)
            return f"⚠️ 自律検証・構文チェックエラーが発生したため、変更をロールバックしました ({target_path.name}):\n{error_msg}\nエラー原因を分析・修復して再度コードを出力してください。"
        return None

    async def execute_tools(self, current_response: str) -> Tuple[str, List[dict]]:
        """
        ツールタグをパースして実行し、更新されたテキストとSSEイベントのリストを返す。
        """
        self.tool_results = []
        self.has_escalation = False
        events = []
        
        # 1. ワークスペースの変更検知と自動スナップショット
        if self.mode in ["task", "research"]:
            has_file_modifications = (
                "<file path=" in current_response
                or "<replace path=" in current_response
                or "<edit path=" in current_response
            )
            if has_file_modifications:
                if self.mode == "research":
                    error_msg = "Researchモードではファイルの書き換えは許可されていません。ファイル操作をキャンセルしました。"
                    logger.error(error_msg)
                    self.tool_results.append(error_msg)
                    current_response += f"\n\n*[⚠️ {error_msg}]*\n\n"
                else:
                    git_snapshot(str(BASE_WORKSPACE_DIR), "Auto-snapshot before AI modification")
                    mod_paths = re.findall(r'<(?:file|replace|edit)\s+path=(["\'])(.*?)\1', current_response)
                    
                    # 🔴 事前探索・認知精度強制チェック (Reconnaissance Enforcement)
                    has_reconnaissance = any(tag in current_response for tag in ["<list_dir", "<read_file", "<view_file", "<grep_search", "<search_codebase", "<run_command"])
                    if not has_reconnaissance and not self.tool_results:
                        logger.warning("事前探索なしのファイル変更を検知。注意コンテキストを付与します。")
                        self.tool_results.append("⚠️ 【事前探索・認知チェック警告】 事前に <list_dir> や <read_file>、<search_codebase> 等でディレクトリ構造や既存コードを確認せずに変更しようとしています。見当違いのパスや初期テンプレートを触る認知エラーを防ぐため、必ずターゲットファイルの中身と構造を確認してから実装してください。")

                    current_response = self._handle_file_creations(current_response)
                    current_response = await self._handle_file_edits(current_response)
                    current_response = self._handle_file_replacements(current_response)

                    # Multi-file coordination (path ledger + agent hint)
                    try:
                        from app.core.multi_file_coordinator import coordinate_after_writes
                        written = [p for _, p in set(mod_paths)]
                        coord = coordinate_after_writes(written)
                        if len(written) > 1 and coord.get("hint"):
                            self.tool_results.append(
                                f"📎 {coord.get('message')}\n{coord.get('hint')}"
                            )
                    except Exception as e:
                        logger.warning(f"multi_file_coordinator: {e}")
                    
                    # 🔴 自律テスト・自動ビルド検証エンジンの完全結合
                    try:
                        from app.core.auto_test_pipeline import run_auto_test
                        for _, p in set(mod_paths):
                            res = await run_auto_test(p, self.session_id, self.mode, max_retries=1)
                            if not res.get("success"):
                                # 嘘発言（ハルシネーション完了宣言）を遮断・ミュートする
                                from app.core.fact_filter import filter_build_hallucination
                                current_response = filter_build_hallucination(current_response, is_build_failed=True)
                                err_msg = f"⚠️ 自律ビルド/テスト検証エラー ({p}):\n{res.get('output')}\n\n【🚀 推論(CoT)および自己修復強制命令】\n上記エラーを消すために『any』型や『@ts-ignore』等の場当たり的な逃げパッチを書くことは厳格に禁止します！\n必ず思考ブロックで「1.なぜエラーが発生したのか 2.影響範囲 3.妥協コードでないか」を3行以上深く推論してから、根本的な解決コードを出力してエラー0件を実証してください。"
                                logger.warning(f"自動テスト検出エラー: {err_msg}")
                                self.tool_results.append(err_msg)
                    except Exception as e:
                        logger.warning(f"自動テストパイプライン実行例外: {e}")

        # 2. URLスクレイピング
        current_response, scrape_events = await self._handle_url_scraping(current_response)
        events.extend(scrape_events)

        # 3. Docker サンドボックスコマンド群
        if self.mode in ["task", "research"]:
            has_docker_tools = (
                re.search(r'<run_command>', current_response) or 
                re.search(r'<read_file', current_response) or 
                re.search(r'<list_dir', current_response)
            )
            if has_docker_tools:
                current_response, docker_events = self._handle_docker_tools(current_response)
                events.extend(docker_events)

        # 3.5. MCP (Model Context Protocol) ツール実行
        if "<mcp_call" in current_response:
            current_response, mcp_events = await self._handle_mcp_tools(current_response)
            events.extend(mcp_events)

        # 4. エスカレーション
        escalate_match = re.search(r'<escalate>\n?(.*?)\n?<\/escalate>', current_response, re.DOTALL)
        if escalate_match:
            self.escalation_history.append(escalate_match.group(1).strip())
            self.has_escalation = True
            events.append({"type": "chunk", "content": f"\n\n*[⚠️ 調査結果を思考モデルにエスカレーション（差し戻し）します]*\n\n"})

        # 4.5. Codebase Search (コードベース横断検索およびgrep_searchエイリアス)
        if "<search_codebase" in current_response or "<grep_search" in current_response:
            # Kairiが出力した <grep_search query="..." ... /> を正規の <search_codebase query="..." /> に変換
            current_response = re.sub(r'<grep_search\s+query=(["\'])(.*?)\1[^>]*\/?>', r'<search_codebase query=\1\2\1 />', current_response)
            from app.core.tools.codebase_search import handle_search_codebase_tag
            current_response, cb_results = await handle_search_codebase_tag(
                current_response, str(BASE_WORKSPACE_DIR)
            )
            if cb_results:
                self.tool_results.extend(cb_results)

        # 5. Web Search & News Search
        import asyncio
        queries = []
        news_queries = []
        
        for match in re.finditer(r'<search\s+query=([\'"”]?)(.*?)\1\s*/?>', current_response):
            q = match.group(2).strip()
            if q and q not in queries: queries.append(q)
                
        for match in re.finditer(r'<search_news\s+query=([\'"”]?)(.*?)\1\s*/?>', current_response):
            q = match.group(2).strip()
            if q and q not in news_queries: news_queries.append(q)
            
        for match in re.finditer(r'<search>\s*<query>(.*?)</query>\s*</search>', current_response, re.DOTALL):
            q = match.group(1).strip()
            if q and q not in queries: queries.append(q)

        legacy_search = re.search(r'<search>\n*(- query: .*?\n?)+\n*<\/search>', current_response, re.DOTALL)
        if legacy_search:
            block = legacy_search.group(0)
            qs = re.findall(r'- query: (.+)', block)
            for q in qs:
                q = q.strip()
                if q and q not in queries: queries.append(q)

        # --- 一般検索 (Brave) の実行 ---
        if queries:
            tasks = []
            for query in queries:
                logger.info(f"🔍 一般検索ツールを実行します: {query}")
                events.append({"type": "status", "status": "searching", "query": query})
                tasks.append(web_search(query))
                
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, res in enumerate(results):
                q = queries[i]
                if isinstance(res, Exception):
                    logger.error(f"❌ 検索ツールエラー: {res}", exc_info=True)
                    self.tool_results.append(f"【検索エラー: {q}】\n{str(res)}")
                else:
                    results_text, sources = res
                    if sources:
                        events.append({"type": "sources", "data": sources})
                    self.tool_results.append(f"【一般検索結果: {q}】\n{results_text}")
                    
            current_response = re.sub(r'<search\s+query=[^>]+>', f"\n\n*[🔍 一般検索完了 ({len(queries)}件)]*\n\n", current_response)
            current_response = re.sub(r'<search>\s*<query>.*?</query>\s*</search>', f"\n\n*[🔍 一般検索完了 ({len(queries)}件)]*\n\n", current_response, flags=re.DOTALL)

        # --- ニュース検索（プール優先 → ライブRSS） ---
        if news_queries:
            tasks = []
            for query in news_queries:
                logger.info(f"📰 ニュース検索ツールを実行します: {query}")
                events.append({"type": "status", "status": "searching", "query": query})
                tasks.append(web_search(query, providers=["news"]))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            used_pool = False

            for i, res in enumerate(results):
                q = news_queries[i]
                if isinstance(res, Exception):
                    logger.error(f"❌ ニュース検索エラー: {res}", exc_info=True)
                    self.tool_results.append(f"【ニュース検索エラー: {q}】\n{str(res)}")
                else:
                    results_text, sources = res
                    this_pool = False
                    if sources:
                        events.append({"type": "sources", "data": sources})
                        this_pool = any(
                            str(s.get("source") or "").startswith("POOL")
                            for s in sources
                        )
                        if this_pool:
                            used_pool = True
                    label = "ニュースDB検索結果" if this_pool else "ニュース検索結果"
                    self.tool_results.append(f"【{label}: {q}】\n{results_text}")

            status = (
                f"\n\n*[📰 ニュースDB検索完了 ({len(news_queries)}件)]*\n\n"
                if used_pool
                else f"\n\n*[📰 ニュース検索完了 ({len(news_queries)}件)]*\n\n"
            )
            current_response = re.sub(r'<search_news\s+query=[^>]+>', status, current_response)
            if legacy_search:
                current_response = current_response.replace(legacy_search.group(0), f"\n\n*[🔍 複数検索完了 ({len(queries)}件)]*\n\n")

        return current_response, events

    def _handle_file_creations(self, current_response: str) -> str:
        file_blocks = re.findall(r'<file\s+path=(["\'])(.*?)\1>\n?([\s\S]*?)<\/file>', current_response)
        for _, path_str, content in file_blocks:
            mock_error = self.check_mocks(content)
            if mock_error:
                logger.error(f"モック検出 ({path_str}): {mock_error}")
                self.tool_results.append(mock_error)
                continue

            try:
                clean_content = self.clean_markdown_block(content)
                safe_path = normalize_safe_path(str(BASE_WORKSPACE_DIR), path_str)
                target_path = BASE_WORKSPACE_DIR / safe_path
                target_path.parent.mkdir(parents=True, exist_ok=True)
                
                is_new_file = not target_path.exists()
                original_content = None
                if not is_new_file:
                    with open(target_path, "r", encoding="utf-8") as f:
                        original_content = f.read()
                        
                with open(target_path, "w", encoding="utf-8") as f:
                    f.write(clean_content + "\n")

                try:
                    from app.core.workspace_state import record_change
                    record_change(
                        safe_path,
                        original_content or "",
                        clean_content + "\n",
                        "create" if is_new_file else "write",
                    )
                except Exception:
                    pass
                    
                lint_error = self.run_linter(target_path, is_new_file, original_content)
                if lint_error:
                    logger.error(lint_error)
                    self.tool_results.append(lint_error)
                    current_response += f"\n\n*[⚠️ {lint_error}]*\n\n"
                    continue

                success_msg = f"ファイル {safe_path} を新規作成・全体保存しました。次のステップに進んでください。"
                self.tool_results.append(success_msg)
                logger.info(f"AI出力によりファイルを全体保存しました: {target_path}")
            except (PermissionError, IsADirectoryError) as e:
                err_msg = (
                    f"ファイル保存エラー ({path_str}): {e}\n"
                    "※同名のディレクトリが既に存在するか、書き込み権限がありません。"
                    "プロジェクト用のサブフォルダ（例: プロジェクト名/ファイル名.ext）を指定して再試行してください。"
                )
                logger.error(err_msg)
                self.tool_results.append(err_msg)
            except Exception as e:
                err_msg = f"ファイル自動保存エラー ({path_str}): {e}（pathはワークスペース相対パスで指定してください）"
                logger.error(err_msg)
                self.tool_results.append(err_msg)
                
        current_response = re.sub(r'<file\s+path=(["\'])(.*?)\1>\n?[\s\S]*?<\/file>', r'\n\n*[📝 ファイル `\2` を作成・保存しました]*\n\n', current_response)
        return current_response

    async def _handle_file_edits(self, current_response: str) -> str:
        """<edit path="..."> タグを Fast Apply（マージ専用LLM）で処理する。

        Executor は変更行だけを「// ... existing code ...」マーカー付きで出力し、
        apply モデルが元ファイルとマージする。検証失敗時は書き込まず、
        Executor に <replace> / <file> へのフォールバックを促す。
        """
        edit_pattern = re.compile(
            r'<edit\s+path=(["\'])(?P<path>.*?)\1'
            r'(?:\s+instruction=(["\'])(?P<instruction>.*?)\3)?\s*>'
            r'\n?(?P<snippet>[\s\S]*?)<\/edit>'
        )
        if not edit_pattern.search(current_response):
            return current_response

        from app.core.fast_apply import apply_edit

        for match in edit_pattern.finditer(current_response):
            path_str = match.group("path")
            instruction = match.group("instruction") or ""
            snippet = match.group("snippet")

            mock_error = self.check_mocks(snippet)
            if mock_error:
                logger.error(f"モック検出 ({path_str}): {mock_error}")
                self.tool_results.append(mock_error)
                continue

            try:
                clean_snippet = self.clean_markdown_block(snippet)
                safe_path = normalize_safe_path(str(BASE_WORKSPACE_DIR), path_str)
                target_path = BASE_WORKSPACE_DIR / safe_path

                if not target_path.exists():
                    err_msg = f"Fast Apply編集エラー: ファイルが存在しません ({path_str})。新規作成する場合は <file path=\"{path_str}\"> を使用してください。"
                    logger.warning(err_msg)
                    self.tool_results.append(err_msg)
                    current_response += f"\n\n*[⚠️ {err_msg}]*\n\n"
                    continue

                with open(target_path, "r", encoding="utf-8") as f:
                    original_content = f.read()

                success, result = await apply_edit(original_content, clean_snippet, instruction)
                if not success:
                    err_msg = (
                        f"Fast Apply編集失敗 ({path_str}): {result}\n"
                        "ファイルは変更されていません。<replace> タグ（<search>/<replace_with>）で"
                        "ピンポイント置換するか、対象箇所を <read_file> で再確認してください。"
                    )
                    logger.warning(err_msg)
                    self.tool_results.append(err_msg)
                    current_response += f"\n\n*[⚠️ {err_msg}]*\n\n"
                    continue

                with open(target_path, "w", encoding="utf-8") as f:
                    f.write(result)

                try:
                    from app.core.workspace_state import record_change
                    record_change(safe_path, original_content or "", result, "edit")
                except Exception:
                    pass

                lint_error = self.run_linter(target_path, is_new_file=False, original_content=original_content)
                if lint_error:
                    logger.error(lint_error)
                    self.tool_results.append(lint_error)
                    current_response += f"\n\n*[⚠️ {lint_error}]*\n\n"
                    continue

                success_msg = f"ファイル {safe_path} にFast Apply編集を適用しました。次のステップに進んでください。"
                self.tool_results.append(success_msg)
                logger.info(f"Fast Apply編集を適用しました: {target_path}")
            except Exception as e:
                err_msg = f"Fast Apply編集エラー ({path_str}): {e}"
                logger.error(err_msg)
                self.tool_results.append(err_msg)

        current_response = edit_pattern.sub(r'\n\n*[📝 ファイル `\g<path>` にFast Apply編集を適用しました]*\n\n', current_response)
        return current_response

    def _handle_file_replacements(self, current_response: str) -> str:
        replace_blocks = re.findall(r'<replace\s+path=(["\'])(.*?)\1>\n*<search>\n?(.*?)\n?<\/search>\n*<replace_with>\n?(.*?)\n?<\/replace_with>\n*<\/replace>', current_response, re.DOTALL)
        for _, path_str, search_text, replace_text in replace_blocks:
            mock_error = self.check_mocks(replace_text)
            if mock_error:
                logger.error(f"モック検出 ({path_str}): {mock_error}")
                self.tool_results.append(mock_error)
                current_response += f"\n\n*[⚠️ コードレビュー警告: {mock_error}]*\n\n"
                continue

            try:
                clean_search = self.clean_markdown_block(search_text)
                clean_replace = self.clean_markdown_block(replace_text)
                safe_path = normalize_safe_path(str(BASE_WORKSPACE_DIR), path_str)
                target_path = BASE_WORKSPACE_DIR / safe_path
                
                if not target_path.exists():
                    err_msg = f"差分置換エラー: ファイルが存在しません ({path_str})。新規作成する場合は <file path=\"{path_str}\"> を使用してください。"
                    logger.warning(err_msg)
                    self.tool_results.append(err_msg)
                    current_response += f"\n\n*[⚠️ {err_msg}]*\n\n"
                    continue
                    
                with open(target_path, "r", encoding="utf-8") as f:
                    file_content = f.read()
                    
                if clean_search not in file_content:
                    logger.warning(f"差分置換エラー: 検索対象が見つかりませんでした ({path_str})")
                    # フォールバック置換を試行
                    from app.core.file_edit_fallback import try_replace_with_context
                    success, result = try_replace_with_context(target_path, clean_search, clean_replace)
                    if success:
                        try:
                            from app.core.workspace_state import record_change
                            after = target_path.read_text(encoding="utf-8")
                            record_change(safe_path, file_content, after, "replace")
                        except Exception:
                            pass
                        success_msg = f"ファイル {safe_path} をフォールバック置換しました。"
                        self.tool_results.append(success_msg)
                        logger.info(f"フォールバック置換成功: {target_path}")
                        continue
                    else:
                        err_msg = f"置換対象のテキストが見つかりませんでした ({path_str})。ファイルの最新内容: {result[:200] if result else 'N/A'}"
                        self.tool_results.append(err_msg)
                        current_response += f"\n\n*[⚠️ {err_msg}]*\n\n"
                        continue
                        
                new_content = file_content.replace(clean_search, clean_replace, 1)
                with open(target_path, "w", encoding="utf-8") as f:
                    f.write(new_content)

                try:
                    from app.core.workspace_state import record_change
                    record_change(safe_path, file_content, new_content, "replace")
                except Exception:
                    pass
                    
                lint_error = self.run_linter(target_path, is_new_file=False, original_content=file_content)
                if lint_error:
                    logger.error(lint_error)
                    self.tool_results.append(lint_error)
                    current_response += f"\n\n*[⚠️ {lint_error}]*\n\n"
                    continue

                success_msg = f"ファイル {safe_path} の対象箇所を差分置換しました。次のステップに進んでください。"
                self.tool_results.append(success_msg)
                logger.info(f"AI出力によりファイルを差分置換しました: {target_path}")
            except Exception as e:
                err_msg = f"差分置換エラー ({path_str}): {e}"
                logger.error(err_msg)
                self.tool_results.append(err_msg)
                
        current_response = re.sub(r'<replace\s+path=(["\'])(.*?)\1>\n*<search>\n?.*?\n?<\/search>\n*<replace_with>\n?.*?\n?<\/replace_with>\n*<\/replace>', r'\n\n*[📝 ファイル `\2` を差分置換しました]*\n\n', current_response, flags=re.DOTALL)
        return current_response

    async def _handle_url_scraping(self, current_response: str) -> Tuple[str, List[dict]]:
        events = []
        for match in re.finditer(r'<read_url\s+url=(["\'])(.*?)\1[^>]*>', current_response):
            url = match.group(2).strip()
            events.append({"type": "status", "status": "running_tool"})
            
            text = await fetch_url(url)
            self.tool_results.append(f"URL {url} の全文（Markdown）:\n```markdown\n{text}\n```")
            
            url_block = f"\n\n*[🌐 URL `{url}` をスクレイピングしました]*\n\n"
            current_response = current_response.replace(match.group(0), url_block)
        return current_response, events

    def _handle_docker_tools(self, current_response: str) -> Tuple[str, List[dict]]:
        events = []
        workspace_dir = str(BASE_WORKSPACE_DIR)
        
        # view_file / view_file(AbsolutePath) を正規の read_file に自動変換
        current_response = re.sub(r'<view_file\s+(?:path|AbsolutePath)=(["\'])(.*?)\1[^>]*\/?>', r'<read_file path=\1\2\1 />', current_response, flags=re.IGNORECASE)

        # 1. read_file / list_dir は Docker サンドボックス未依存で常に安全に実行（ホスト側直接フォールバック）
        for match in re.finditer(r'<read_file\s+path=(["\'])(.*?)\1[^>]*>', current_response):
            path = match.group(2).strip()
            output = safe_read_file(workspace_dir, path)
            self.tool_results.append(f"ファイル {path} の内容:\n```\n{output}\n```")
            
            read_block = f"\n\n*[📄 ファイル `{path}` を読み込みました]*\n\n"
            events.append({"type": "chunk", "content": read_block})
            current_response = current_response.replace(match.group(0), read_block)
            
        # list_dir / list_dir path="..." の両対応
        for match in re.finditer(r'<list_dir(?:\s+path=(["\'])(.*?)\1)?[^>]*\/?>', current_response):
            path = match.group(2).strip() if match.group(2) else "."
            output = safe_list_dir(workspace_dir, path)
            self.tool_results.append(f"ディレクトリ {path} の内容:\n```\n{output}\n```")
            
            dir_block = f"\n\n*[📁 ディレクトリを確認しました: `{path}`]*\n\n"
            events.append({"type": "chunk", "content": dir_block})
            current_response = current_response.replace(match.group(0), dir_block)
            
        # 2. run_command は Docker/ホストフォールバックで常に安全に実行
        if re.search(r'<run_command[^>]*>(.*?)</run_command>', current_response, re.DOTALL):
            try:
                sandbox = get_sandbox(self.session_id, workspace_dir)
                for match in re.finditer(r'<run_command[^>]*>(.*?)</run_command>', current_response, re.DOTALL):
                    cmd = match.group(1).strip()
                    
                    # 危険コマンドの事前ブロック
                    dangerous_patterns = [r'^rm\s+-rf\s+/', r'^rm\s+-rf\s+\*', r'^sudo\s+']
                    is_dangerous = False
                    for dp in dangerous_patterns:
                        if re.search(dp, cmd):
                            is_dangerous = True
                            break
                    if is_dangerous:
                        blocked_msg = f"🛡️ Security Block: Command '{cmd}' is blocked for safety reasons."
                        logger.warning(blocked_msg)
                        self.tool_results.append(blocked_msg)
                        events.append({"type": "chunk", "content": f"\n\n*[{blocked_msg}]*\n\n"})
                        current_response = current_response.replace(match.group(0), f"\n\n*[{blocked_msg}]*\n\n")
                        continue
                    
                    # サプライチェーン攻撃・マルウェアスクリプト自動実行防止 (セキュアサニタイズ)
                    if re.search(r'\bnpm\s+(install|i)\b', cmd) and '--ignore-scripts' not in cmd:
                        cmd += " --ignore-scripts"
                        logger.info(f"🛡️ マルウェア・サプライチェーン防衛: npm install に --ignore-scripts を自動付与: {cmd}")

                    events.append({"type": "status", "status": "running_tool"})
                    try:
                        from app.core.workspace_state import record_activity
                        record_activity("run_command", cmd[:200])
                    except Exception:
                        pass
                    
                    terminal_block = f"\n\n```bash\n$ {cmd}\n"
                    events.append({"type": "chunk", "content": terminal_block})
                    current_response += terminal_block
                    
                    raw_output = sandbox.run_command(cmd)
                    output = self.filter_logs(raw_output)
                    
                    terminal_output = f"{output}\n```\n\n"
                    events.append({"type": "chunk", "content": terminal_output})
                    current_response = current_response.replace(match.group(0), terminal_block + terminal_output)
                    
                    self.tool_results.append(f"実行したコマンド: {cmd}\n結果:\n```\n{output}\n```")
            except Exception as e:
                error_msg = f"Dockerサンドボックス初期化エラー: {e}\nDocker Desktopが起動しているか確認してください。"
                self.tool_results.append(error_msg)
                events.append({"type": "chunk", "content": f"\n\n*[⚠️ Dockerエラー: {error_msg}]*\n\n"})
            
        return current_response, events

    async def _resolve_mcp_tool(self, tool_name: str, params: dict):
        """ローカルに無いツール名を外部MCPサーバーのツールとして逆引き解決する。
        "Server->Tool" 連結形式・server= 属性欠落形式を吸収する。"""
        from app.core.mcp import mcp_manager
        # "Server->Tool" 連結形式
        if "->" in tool_name:
            server_name, bare_tool = tool_name.split("->", 1)
            if server_name in mcp_manager.servers:
                res = await mcp_manager.call_tool(server_name, bare_tool, params)
                return res, server_name
            tool_name = bare_tool  # サーバー名不一致時は裸ツール名で逆引きへ
        # ツール名からサーバー逆引き（ターン内キャッシュ付き）
        if not hasattr(self, "_mcp_tool_map"):
            self._mcp_tool_map = {}
        if tool_name not in self._mcp_tool_map:
            for server_name in mcp_manager.servers:
                try:
                    tools = await mcp_manager.list_server_tools(server_name)
                except Exception:
                    continue
                for t in tools or []:
                    if isinstance(t, dict) and t.get("name"):
                        self._mcp_tool_map.setdefault(t["name"], server_name)
                if tool_name in self._mcp_tool_map:
                    break
        server_name = self._mcp_tool_map.get(tool_name)
        if not server_name:
            return None, None
        res = await mcp_manager.call_tool(server_name, tool_name, params)
        return res, server_name

    async def _handle_mcp_tools(self, current_response: str) -> Tuple[str, List[dict]]:
        """MCP (Model Context Protocol) タグをパースして外部/ローカルツールを実行する"""
        events = []
        
        # パターン1: server属性あり → MCPサーバー経由
        mcp_blocks = re.findall(r'<mcp_call\s+server=(["\'])(.*?)\1\s+tool=(["\'])(.*?)\3\s+args=(["\'])(.*?)\5\s*\/?>', current_response)
        if not mcp_blocks:
            mcp_blocks = re.findall(r'<mcp_call\s+server=(["\'])(.*?)\1\s+tool=(["\'])(.*?)\3\s*>\n?([\s\S]*?)<\/mcp_call>', current_response)
        
        for match in mcp_blocks:
            server_name = match[1]
            tool_name = match[3]
            args_str = match[4] if len(match) == 6 else match[5]
            
            try:
                args = json.loads(args_str) if args_str else {}
            except Exception:
                args = {"raw_input": args_str}
            
            try:
                from app.core.mcp import mcp_manager
                res = await mcp_manager.call_tool(server_name, tool_name, args)
            except Exception as e:
                res = f"[ERROR] MCPサーバー呼び出し失敗: {e}"
            
            self.tool_results.append(f"[MCP Tool: {server_name}->{tool_name}]\n{res}")
            mcp_block = f"\n\n*[🔌 MCPツール実行: `{server_name}/{tool_name}`]*\n\n"
            events.append({"type": "chunk", "content": mcp_block})
            
            if len(match) == 6:
                full_tag_pattern = rf'<mcp_call\s+server=["\']?{re.escape(server_name)}["\']?\s+tool=["\']?{re.escape(tool_name)}["\']?\s+args=["\']?{re.escape(args_str)}["\']?\s*\/>'
            else:
                full_tag_pattern = rf'<mcp_call\s+server=["\']?{re.escape(server_name)}["\']?\s+tool=["\']?{re.escape(tool_name)}["\']?\s*>[\s\S]*?<\/mcp_call>'
            current_response = re.sub(full_tag_pattern, mcp_block, current_response, count=1)
        
        # パターン2: server属性なし → ローカルToolRegistry経由
        local_tool_blocks = re.findall(r'<mcp_call\s+tool=(["\'])(.*?)\1(?:\s+([a-zA-Z_]+)=(["\'])(.*?)\4)*\s*\/?>', current_response)
        if not local_tool_blocks:
            local_tool_blocks = re.findall(r'<mcp_call\s+tool=(["\'])(.*?)\1\s*>([\s\S]*?)<\/mcp_call>', current_response)
        
        # 簡易パース: tool名＋key=value のパターン
        for tool_match in re.finditer(r'<mcp_call\s+tool=(["\'])(.*?)\1([^>]*)\/?>', current_response):
            tool_name = tool_match.group(2)
            attr_part = tool_match.group(3).strip()
            
            # key=value をパース
            params = {}
            for kv in re.findall(r'([a-zA-Z_]+)=(["\'])(.*?)\2', attr_part):
                params[kv[0]] = kv[2]
            
            if tool_name:
                from app.core.tools.registry import tool_registry
                if tool_registry.get_tool(tool_name):
                    res = tool_registry.execute(tool_name, params)
                    self.tool_results.append(f"[Local Tool: {tool_name}]\n{res}")
                else:
                    # ローカルに無いツール名 → 外部MCPサーバーのツールとして逆引き解決を試みる
                    # （"Server->Tool" 連結形式や server= 属性欠落形式を吸収）
                    res, used_server = await self._resolve_mcp_tool(tool_name, params)
                    if used_server:
                        self.tool_results.append(f"[MCP Tool: {used_server}->{tool_name}]\n{res}")
                    else:
                        # 解決できなければ従来の不明ツールエラー（外部サーバー案内付き）
                        res = tool_registry.execute(tool_name, params)
                        self.tool_results.append(f"[Local Tool: {tool_name}]\n{res}")
                mcp_block = f"\n\n*[🔧 ローカルツール実行: `{tool_name}`]*\n\n"
                events.append({"type": "chunk", "content": mcp_block})
                full_tag = tool_match.group(0)
                current_response = current_response.replace(full_tag, mcp_block, 1)
        
        # 全ツール実行結果に対する不可視文字・間接プロンプトインジェクション防御サニタイズ適用
        from app.core.fact_filter import sanitize_indirect_prompt_injection
        self.tool_results = [sanitize_indirect_prompt_injection(str(tr)) for tr in self.tool_results]

        return current_response, events
