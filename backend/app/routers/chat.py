"""
チャット API ルーター — SSE ストリーミング対応（仕様書 §1-3 準拠）。

処理フロー:
1. リクエスト受信 → プロンプト構築
2. LLM に送信（非ストリーミングで全文取得）
3. <thinking> をパース → require_search 判定
4. 検索必要時: バッファ破棄 → 検索 → 再生成
5. <response> の内容を SSE で逐次送信
6. 完了後、会話履歴を SQLite に保存 + KV 書き込み
"""
import json
import re
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.models.chat import ChatRequest
from app.core.prompt_builder import build_system_instruction
from app.core.kv_store import kv_store
from app.core.mood import get_mood
from app.utils.logger import get_logger
from app.routers.settings import app_settings
from app.core.cache_manager import get_llm_cache, set_llm_cache, should_bypass_llm_cache
from app.core.gyaru import to_hyper_gal_v3
from app.core import chat_search
from app.core.chat_search import (
    store_search_carryover as _store_search_carryover,
    maybe_carry_search_results as _maybe_carry_search_results,
    clip_search_results as _clip_search_results,
    extract_smart_snippet as _extract_smart_snippet,
    sanitize_conversational_query,
    balance_search_queries,
    run_web_search,
    finalize_search_context,
)
from app.core.chat_persist import (
    get_conversation_messages as _get_conversation_messages,
    save_messages as _save_messages,
)
from app.core.chat_modes import try_greeting_mode, try_char_mode
from app.core.chat_orchestrator import (
    build_executor_instruction,
    apply_omakase_hearing_ban,
    apply_post_spec_approval_gate,
    compose_hearing_user_text,
    compose_spec_user_text,
    is_continuation_utterance,
    is_plan_approval_utterance,
    resolve_memory_inject,
    note_search_inject,
    should_emit_reasoning,
)

logger = get_logger(__name__)

router = APIRouter()

# セッションごとのフォローアップ履歴（インメモリ、サーバー再起動でリセット）
_MAX_FOLLOWUP_SESSIONS = 200
_followup_histories: dict[str, list[bool]] = {}

# evals 互換: carryover ストアへの参照
_last_search_by_session = chat_search._last_search_by_session


def _sse_event(data: dict) -> str:
    """SSE イベントをフォーマット"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat")
async def chat(request: ChatRequest):
    """メッセージ送信 → SSE ストリーミング応答"""
    session_id = request.session_id
    user_input = request.message
    mode = request.mode

    if not user_input or not user_input.strip():
        raise HTTPException(status_code=400, detail="メッセージを入力してください。")
    if not session_id:
        raise HTTPException(status_code=400, detail="セッションIDが必要です。")

    # フォローアップ・クールダウン判定（demo.py のロジック移植）
    # メモリリーク防止: 古いセッションを自動削除
    if len(_followup_histories) >= _MAX_FOLLOWUP_SESSIONS and session_id not in _followup_histories:
        oldest_key = next(iter(_followup_histories))
        del _followup_histories[oldest_key]
    history = _followup_histories.setdefault(session_id, [])
    followup_cooldown = len(history) >= 2 and all(history[-2:])

    # KV フィルタリング + KV一覧 + プロンプト構築
    # ※ filter_by_scope はオプトイン（明示許可 or キーワード一致のみ）。空なら注入しない。
    from app.core.memory_policy import user_allows_memory_use
    relevant_kv = await kv_store.filter_by_scope(user_input)
    filtered_kv_text = kv_store.format_for_prompt(relevant_kv) if relevant_kv else ""
    # 全件一覧は「記憶を使って/覚えてる？」等の明示時のみ Supervisor に渡す（漏洩防止）
    kv_summary = await kv_store.format_summary() if user_allows_memory_use(user_input) else ""
    mood = get_mood()

    # --- ギャルモード (Lv3 Hyper Gal / omous Engine) 判定 ---
    settings_dict = app_settings.get()
    is_hyper_gal = (
        settings_dict.get("persona_style") in ["hyper_gal", "gal", "gyaru"]
        or ("ギャル" in user_input and "解除" not in user_input)
        or "lv3_gal" in user_input.lower()
    )

    # DB から会話履歴を取得
    messages = await _get_conversation_messages(session_id)

    async def event_stream():
        nonlocal mode, filtered_kv_text, kv_summary, user_input
        final_accumulated_response = ""
        from app.core.search_planner import plan_search
        from app.core.supervisor import run_supervisor
        from app.core.executor import run_executor
        from app.core.ui_status import pipeline_detail

        _ui_locale = app_settings.get().get("locale", "en")

        # --- Greeting / Char short-circuit ---
        async for ev in try_greeting_mode(
            user_input=user_input,
            mode=mode,
            force_search=request.force_search,
            messages=messages,
            filtered_kv_text=filtered_kv_text,
            is_hyper_gal=is_hyper_gal,
            session_id=session_id,
        ):
            if ev.get("type") == "_handled":
                return
            yield _sse_event(ev)

        async for ev, updated_input in try_char_mode(
            user_input=user_input,
            mode=mode,
            messages=messages,
            filtered_kv_text=filtered_kv_text,
            is_hyper_gal=is_hyper_gal,
            session_id=session_id,
        ):
            if updated_input is not None:
                user_input = updated_input
            if ev.get("type") == "_handled":
                return
            yield _sse_event(ev)

        # --- 🔴 P0: Plan承認検出（短い承認語のみ。続き指示は誤ヒットさせない） ---
        if mode in ["chat", "task"]:
            try:
                kv_items = await kv_store.filter_by_scope("pending_plan")
                for item in kv_items:
                    summary = item.get("summary", {})
                    if summary.get("target") != "pending_plan":
                        continue
                    # 「続きを作成して」等は incomplete 再開用。古い plan 注入を禁止し KV を捨てる
                    if is_continuation_utterance(user_input):
                        logger.info(
                            "続き指示のため pending_plan を破棄（誤承認防止）: %s",
                            user_input[:40],
                        )
                        try:
                            await kv_store.delete(item["id"])
                        except Exception as e:
                            logger.warning(f"Failed to delete pending plan {item['id']}: {e}")
                        break
                    if not is_plan_approval_utterance(user_input):
                        continue
                    logger.info("✅ Plan承認検出: 実装モードに移行")
                    mode = "task"
                    plan_note = summary.get("note", "")
                    if plan_note:
                        user_input = (
                            f"{user_input}\n\n【承認済みプラン】\n{plan_note}\n"
                            "上記プランを直ちに実行せよ。"
                        )
                    try:
                        await kv_store.delete(item["id"])
                    except Exception as e:
                        logger.warning(f"Failed to delete pending plan {item['id']}: {e}")
                    break
            except Exception as e:
                logger.warning(f"Error processing pending plan approval: {e}")
        
        # --- 🔴 P0: ユーザー発言内に直接URLが含まれる場合の自動ディープスクレイピング ---
        url_matches = re.findall(r'https?://[^\s)\]"]+', user_input)
        direct_url_texts = []
        if url_matches:
            from app.core.search.router import fetch_url
            for u in url_matches[:2]:
                yield _sse_event({"type": "status", "status": "scraping_url", "url": u})
                try:
                    content = await fetch_url(u)
                    if content and len(content.strip()) > 50:
                        snippet_content = _extract_smart_snippet(content, 15000)
                        direct_url_texts.append(f"【ユーザー指定URLの直接スクレイピング本文: {u}】\n{snippet_content}")
                        logger.info(f"直接URLフェッチ成功: {u} ({len(snippet_content)} bytes)")
                except Exception as e:
                    logger.warning(f"指定URL事前フェッチ失敗 {u}: {e}")

        # 1. 検索判定 (Search Planner LLM)
        yield _sse_event({"type": "status", "status": "planning_search"})
        yield _sse_event({
            "type": "pipeline",
            "stage": "intent_analysis",
            "detail": pipeline_detail("intent_analysis", _ui_locale),
        })
        
        search_plan = await plan_search(user_input, messages, session_id=session_id)
        search_needed = search_plan["needs_search"] or request.force_search
        search_queries = search_plan.get("search_queries", [])
        chat_category = search_plan.get("category", "general")
        search_providers = search_plan.get("providers", ["brave"])

        if not search_queries:
            search_queries = [sanitize_conversational_query(user_input)]
        else:
            search_queries = [
                sanitize_conversational_query(q)
                if len(q) > 25 and ("ｗ" in q or "思う" in q or "なんだ" in q)
                else q
                for q in search_queries
            ]
        search_needed, search_queries = balance_search_queries(
            user_input, search_needed, search_queries, session_id=session_id
        )

        # --- Intent Routing (Auto Mode Switching) ---
        recommended_mode = search_plan.get("recommended_mode")
        if recommended_mode in ["chat", "task"]:
            mode = recommended_mode
            
        yield _sse_event({"type": "mode_switch", "mode": mode})
        
        # モード確定後にSupervisor用とExecutor用のプロンプトを個別に構築
        static_sys, dynamic_sys, persona_inst = build_system_instruction(
            user_input=user_input,
            mode=mode,
            mood=mood,
            filtered_kv_text=filtered_kv_text,
            followup_cooldown=followup_cooldown,
            kv_summary=kv_summary,
            history_messages=messages,
        )
        supervisor_sys_prompt = persona_inst + "\n\n" + static_sys
        supervisor_dynamic_sys = dynamic_sys
        
        executor_static, executor_dynamic, _ = build_system_instruction(
            user_input=user_input,
            mode=mode,
            mood=mood,
            filtered_kv_text="",  # Executorにはここで渡さない (memory_to_injectで注入する)
            followup_cooldown=followup_cooldown,
            kv_summary="",  # Executorには全記憶を絶対に渡さない（トークン節約＆ハルシネーション防止）
            history_messages=messages,
        )
        executor_sys_prompt = persona_inst + "\n\n" + executor_static
        executor_sys_prompt += "\n\n【ツール使用時の厳格なルール】\n<read_url>, <search>, <file>, <replace>, <run_command> 等のツールタグを出力した後は、**そのタグを出力した時点で即座にテキスト生成を停止し、システムからの実行結果の返却を待つこと。** 「実行中です」「スクレイピングしてくるわ」などの擬似的な演出テキストをタグの前後に追加することは絶対に禁止します。"
        executor_dynamic_sys = executor_dynamic
        
        if mode in ["task", "research"]:
            from app.routers.workspace import get_workspace_files_text
            workspace_text = get_workspace_files_text()
            user_input_with_context = f"{user_input}\n\n【現在のワークスペースのファイル（参考）】\n{workspace_text}"
        else:
            user_input_with_context = user_input
        
        search_results_text = None
        search_sources = []

        if search_needed:
            async for ev in run_web_search(
                user_input=user_input,
                search_queries=search_queries,
                search_providers=search_providers,
                session_id=session_id,
            ):
                if ev.get("type") == "_result":
                    search_results_text = ev.get("text")
                    search_sources = ev.get("sources") or []
                else:
                    yield _sse_event(ev)

        search_results_text, search_unsupported = finalize_search_context(
            session_id=session_id,
            user_input=user_input,
            messages=messages,
            search_needed=search_needed,
            search_queries=search_queries,
            search_results_text=search_results_text,
            direct_url_texts=direct_url_texts,
        )

        max_supervisor_loops = 2
        supervisor_loop_count = 0
        escalation_history = []
        
        while supervisor_loop_count < max_supervisor_loops:
            supervisor_loop_count += 1
            
            # 2. 思考モデル (V4 Pro)
            yield _sse_event({"type": "status", "status": "thinking"})
            yield _sse_event({
                "type": "pipeline",
                "stage": "fact_checking",
                "detail": pipeline_detail("fact_checking", _ui_locale),
            })
            
            current_user_input_with_context = user_input_with_context
            if escalation_history:
                escalation_msg = "\n\n【Executorからの差し戻し（エスカレーション）情報】\n" + "\n---\n".join(escalation_history)
                current_user_input_with_context += escalation_msg
            
            # 🔴 LLM応答キャッシュチェック（Supervisor呼び出し前）
            from app.routers.settings import app_settings as settings_module
            _settings = settings_module.get()
            _provider = _settings.get("supervisor_provider", "deepseek")
            _model = _settings.get("supervisor_model", "deepseek-v4-flash")
            
            # 鮮度必須（検索必須・時事/市場）のみ LLM キャッシュを bypass。「教えて」等の口語では飛ばさない
            bypass_cache, bypass_reason = should_bypass_llm_cache(
                search_needed=search_needed,
                category=chat_category,
                user_input=user_input,
            )
            if bypass_cache:
                cached_response = None
                logger.info(f"⏭️ Supervisorキャッシュbypass: {bypass_reason} ({user_input[:30]}...)")
            else:
                cached_response = await get_llm_cache(
                    user_input=current_user_input_with_context,
                    system_prompt=supervisor_sys_prompt,
                    mode=mode,
                    model=_model,
                    provider=_provider,
                    max_age_seconds=1800,
                )
            
            # IBKR 口座照会は Supervisor LLM を飛ばす（空JSONフォールバック対策）
            from app.core.ibkr.intent import ibkr_supervisor_shortcut

            ibkr_short = ibkr_supervisor_shortcut(user_input)
            if ibkr_short:
                logger.info(f"🏦 IBKR supervisor shortcut: {user_input[:40]}...")
                supervisor_json, reasoning = ibkr_short, ""
            elif cached_response:
                logger.info(f"⚡ Supervisorキャッシュヒット: {user_input[:30]}...")
                supervisor_json = cached_response["supervisor_json"]
                reasoning = cached_response.get("reasoning", "")
            else:
                try:
                    supervisor_json, reasoning = await run_supervisor(
                        user_input=current_user_input_with_context + "\n\n【動的システムコンテキスト】\n" + supervisor_dynamic_sys,
                        search_results=search_results_text,
                        memory_text=filtered_kv_text,
                        history_messages=messages,
                        mode=mode,
                        system_instruction=supervisor_sys_prompt,
                        category=chat_category,
                    )
                    # bypass 時は SET しない（LRU 汚染・見かけの hit rate 低下を防ぐ）
                    if not bypass_cache:
                        await set_llm_cache(
                            user_input=current_user_input_with_context,
                            system_prompt=supervisor_sys_prompt,
                            mode=mode,
                            model=_model,
                            provider=_provider,
                            response=json.dumps(supervisor_json, ensure_ascii=False),
                            reasoning=reasoning,
                            supervisor_json=supervisor_json,
                            ttl_seconds=1800,
                        )
                except Exception as e:
                    logger.error(f"Supervisor error: {e}")
                    yield _sse_event({
                        "type": "error",
                        "message": pipeline_detail("system_error", _ui_locale),
                        "detail": str(e),
                    })
                    return
            
            # バックグラウンド処理: メモリ抽出 (Supervisor判断 + コード側ゲートで拒否)
            kv_action = supervisor_json.get("kv_action")
            if kv_action and isinstance(kv_action, dict) and kv_action.get("action") in ["add", "update", "delete"]:
                from app.core.memory_policy import should_accept_kv_action
                accepted, reason = should_accept_kv_action(user_input, kv_action)
                if not accepted:
                    logger.warning(
                        f"KV保存を拒否 (reason={reason}): "
                        f"action={kv_action.get('action')} target={kv_action.get('summary', {}).get('target')}"
                    )
                    supervisor_json["kv_action"] = {"action": "none", "rejected_reason": reason}
                else:
                    try:
                        action = kv_action.get("action")
                        if action == "add":
                            await kv_store.add(kv_action)
                            logger.info(
                                f"Supervisor指示によるメモリ追加: "
                                f"{kv_action.get('summary', {}).get('target')} ({reason})"
                            )
                        elif action == "update" and kv_action.get("target_id"):
                            target_id = int(kv_action["target_id"])
                            await kv_store.update(target_id, kv_action)
                            logger.info(f"Supervisor指示によるメモリ更新: ID {target_id}")
                        elif action == "delete" and kv_action.get("target_id"):
                            target_id = int(kv_action["target_id"])
                            await kv_store.delete(target_id)
                            logger.info(f"Supervisor指示によるメモリ削除: ID {target_id}")

                        # KVメモリが更新されたので、プロンプト用のテキストを再生成する
                        relevant_kv = await kv_store.filter_by_scope(user_input)
                        filtered_kv_text = kv_store.format_for_prompt(relevant_kv)
                        if any(k in user_input for k in ["メモリ", "記憶", "覚えて", "KV", "プロフィール"]):
                            filtered_kv_text = "（ユーザーの記憶やプロフィールを確認する場合は <internal_kv_state> を参照してください）"
                        kv_summary = await kv_store.format_summary()

                        # Supervisor向けにプロンプトを再構築 (エスカレーション再試行用)
                        retry_static, retry_dynamic = build_system_instruction(
                            user_input=user_input,
                            mode=mode,
                            mood=mood,
                            filtered_kv_text=filtered_kv_text,
                            followup_cooldown=followup_cooldown,
                            kv_summary=kv_summary,
                        )
                        supervisor_sys_prompt = retry_static
                        supervisor_dynamic_sys = retry_dynamic
                    except Exception as e:
                        logger.error(f"SupervisorからのKV保存に失敗しました: {e}")

            # モードの強制上書き
            if supervisor_json.get("mode"):
                mode = supervisor_json["mode"]

            mode, supervisor_json = apply_omakase_hearing_ban(user_input, mode, supervisor_json)
            mode, supervisor_json = apply_post_spec_approval_gate(
                user_input, mode, supervisor_json, messages
            )

            # hearing/spec では reasoning を前面に出さない（独白汚染防止）
            # Supervisor JSON/独白風も抑制
            if reasoning and should_emit_reasoning(mode):
                from app.core.fact_filters.markup import looks_like_supervisor_dump

                if looks_like_supervisor_dump(reasoning):
                    logger.info("Supervisor 独白風 reasoning を抑制しました")
                else:
                    yield _sse_event({"type": "reasoning", "content": reasoning})

            if supervisor_json.get("mode"):
                yield _sse_event({"type": "mode_switch", "mode": mode})
            
            if supervisor_json.get("chart_data"):
                yield _sse_event({"type": "chart", "data": supervisor_json["chart_data"]})
            
            if mode == "hearing":
                body = compose_hearing_user_text(supervisor_json)
                if is_hyper_gal and body:
                    body = to_hyper_gal_v3(body)
                if body:
                    yield _sse_event({"type": "chunk", "content": body})
                await _save_messages(
                    session_id, user_input, body, json.dumps(supervisor_json, ensure_ascii=False), supervisor_json, reasoning, search_sources
                )
                yield _sse_event({"type": "done", "content": body, "ok": bool((body or "").strip())})
                return
            
            if mode == "spec_generation":
                body = compose_spec_user_text(supervisor_json)
                if is_hyper_gal and body:
                    body = to_hyper_gal_v3(body)
                if body:
                    yield _sse_event({"type": "chunk", "content": body})
                await _save_messages(
                    session_id, user_input, body, json.dumps(supervisor_json, ensure_ascii=False), supervisor_json, reasoning, search_sources
                )
                yield _sse_event({"type": "done", "content": body, "ok": bool((body or "").strip())})
                return
            
            if mode == "coding":
                mode = "task" # 実行モデル向けにTaskモードとして扱う

            # プラン提示判定 (Planning Mode) — 承認フロー
            if supervisor_json.get("plan"):
                yield _sse_event({"type": "status", "status": "proposing_plan"})
                plan_content = supervisor_json["plan"]
                plan_text = f"<plan>\n{plan_content}\n</plan>\n\n---\n💡 **このプランで進めますか？** 「はい」「OK」「進めて」等で承認、または修正点があれば教えてください。"
                yield _sse_event({"type": "chunk", "content": plan_text})
                
                # プラン情報をDBに保存（次ターンで承認/修正を判定するため）
                await _save_messages(
                    session_id, user_input, plan_text, json.dumps(supervisor_json, ensure_ascii=False), supervisor_json, reasoning, search_sources
                )
                
                # plan_awaiting_approval 状態を設定
                try:
                    await kv_store.add({
                        "action": "add",
                        "category": "agreement",
                        "quote": user_input[:40],
                        "summary": {
                            "target": "pending_plan",
                            "stance": "条件付き",
                            "note": f"承認待ちプラン: {plan_content[:100]}",
                            "tags": ["plan", "approval", "pending"]
                        }
                    })
                except Exception as e:
                    logger.warning(f"Failed to save plan approval request to KV store: {e}")
                
                yield _sse_event({"type": "done", "content": plan_text, "ok": bool((plan_text or "").strip())})
                return

            # 内部仕様書の抽出 (過去の履歴から直近のものを探す)
            internal_spec = None
            for msg in messages:
                if msg.get("thinking_json"):
                    try:
                        parsed = json.loads(msg["thinking_json"])
                        if parsed.get("spec_document") and parsed["spec_document"].get("internal"):
                            internal_spec = parsed["spec_document"]["internal"]
                    except Exception as e:
                        logger.warning(f"Failed to parse thinking_json for spec_document: {e}")
            if supervisor_json.get("spec_document") and supervisor_json["spec_document"].get("internal"):
                internal_spec = supervisor_json["spec_document"]["internal"]
            
            if internal_spec and mode in ["coding", "task"]:
                executor_sys_prompt = f"<spec_internal>\n{internal_spec}\n</spec_internal>\n\n" + executor_sys_prompt

            # 沈黙判定（通常のchatモード等で、回答不要と判断された場合のみここで停止）
            if supervisor_json.get("silence"):
                yield _sse_event({"type": "done", "content": "", "ok": False})
                await _save_messages(
                    session_id, user_input, "", json.dumps(supervisor_json, ensure_ascii=False), supervisor_json, reasoning, search_sources
                )
                return

            # 3. 自律実行ループ（Auto Execution Loop）
            instruction = build_executor_instruction(
                supervisor_json, search_unsupported=search_unsupported
            )
            supervisor_json, memory_to_inject = resolve_memory_inject(
                supervisor_json, filtered_kv_text, user_input=user_input
            )
            search_to_inject = note_search_inject(search_results_text, supervisor_json)

            # auto_execution_loop を使用した自律ループ
            import asyncio
            from app.core.auto_execution_loop import auto_execute_with_retry
            
            sse_queue = asyncio.Queue()
            
            def _yield_sse(data: dict):
                """イベントストリームにyieldする内部関数"""
                nonlocal final_accumulated_response
                if data.get("type") == "chunk":
                    chunk_text = data.get("content", "")
                    final_accumulated_response += chunk_text
                    if is_hyper_gal:
                        return  # ギャルモード時は変換前の本文のchunkをSSEに送らず、完了時のギャル文字一括表示のみ行う
                sse_queue.put_nowait(data)
            
            yield _sse_event({"type": "status", "status": "responding"})
            yield _sse_event({
                "type": "pipeline",
                "stage": "composing",
                "detail": pipeline_detail("composing", _ui_locale),
            })
            
            try:
                exec_task = asyncio.create_task(
                    auto_execute_with_retry(
                        user_input=user_input_with_context,
                        instruction=instruction,
                        supervisor_sys_prompt=supervisor_sys_prompt,
                        supervisor_dynamic_sys=supervisor_dynamic_sys,
                        executor_sys_prompt=executor_sys_prompt,
                        executor_dynamic_sys=executor_dynamic_sys,
                        mode=mode,
                        session_id=session_id,
                        history_messages=messages,
                        search_results=search_to_inject,
                        memory_text=memory_to_inject,
                        max_tool_loops=40,
                        max_supervisor_retries=5,
                        yield_sse_func=_yield_sse,
                    )
                )
                
                while not exec_task.done() or not sse_queue.empty():
                    try:
                        item = await asyncio.wait_for(sse_queue.get(), timeout=0.05)
                        yield _sse_event(item)
                    except asyncio.TimeoutError:
                        continue
                
                ai_response, tool_results_summary, new_escalation = await exec_task
                escalation_history.extend(new_escalation)
            except Exception as e:
                logger.error(f"Auto execution loop error: {e}")
                yield _sse_event({
                    "type": "error",
                    "message": pipeline_detail("system_error", _ui_locale),
                    "detail": str(e),
                })
                return
            
            if escalation_history:
                continue  # supervisor loop retry

            # thinking データ（デバッグ/分析用）
            yield _sse_event({"type": "thinking", "data": supervisor_json})

            # 応答が空（0文字）の場合はエラーとして扱い、DBに保存しない（履歴汚染の防止）
            if not ai_response.strip():
                logger.error(f"⚠️ 最終生成応答が空のため、DB保存をスキップしてエラーイベントを送信します (session_id: {session_id})")
                yield _sse_event({"type": "error", "message": "応答の生成に失敗しました（出力が空です）。時間をおいてもう一度お試しください。"})
                return

            from app.core.completion_status import is_aborted_short_market_reply

            if is_aborted_short_market_reply(ai_response, user_input):
                logger.error(
                    f"⚠️ 市況応答が極端に短いため DB 保存をスキップ (session_id: {session_id}, "
                    f"len={len(ai_response.strip())}, preview={ai_response.strip()[:20]!r})"
                )
                yield _sse_event(
                    {
                        "type": "error",
                        "message": "応答が途中で切れました。もう一度送ってください（市況は再送で続きから取れます）。",
                    }
                )
                return

            if is_hyper_gal and ai_response:
                ai_response = to_hyper_gal_v3(ai_response)

            # バックグラウンド処理: DB保存
            await _save_messages(
                session_id, user_input, ai_response, json.dumps(supervisor_json, ensure_ascii=False), supervisor_json, reasoning, search_sources
            )

            # フォローアップ履歴更新
            needs_followup = bool(supervisor_json.get("needs_followup")) if supervisor_json else False
            history.append(needs_followup)

            # 違反ログの記録 (検索スキップ等の判定)
            violation_risk = supervisor_json.get("violation_risk")
            if not violation_risk and search_needed and not supervisor_json.get("search_used"):
                violation_risk = "検索スキップ"
            
            if violation_risk:
                logger.warning(f"違反検出: {violation_risk} - session_id: {session_id}")
                # 本格的な違反ログDB保存は必要に応じて実装

            # 完了（空洞完了は ok:false）
            from app.core.completion_status import build_done_payload
            yield _sse_event(build_done_payload(ai_response, user_input))

            break  # supervisor loop break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

