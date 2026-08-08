# Kairi — Local market companion chat (BYOK)

[![UI](https://img.shields.io/badge/UI-React_19_%2B_Tailwind_v4-blue)](#)
[![Backend](https://img.shields.io/badge/Backend-FastAPI_%2B_SQLite-green)](#)
[![Models](https://img.shields.io/badge/Models-DeepSeek_%2F_GPT_%2F_Gemini-orange)](#)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

**A local BYOK chat companion that answers “how’s the market today?” for US/JP stocks with search grounding and session-aware dates.**

[日本語 README](README.ja.md)

---

## What it is

Kairi runs on your PC. You bring your own LLM API key (DeepSeek recommended). It focuses on:

1. **Market Q&A** — “How did US markets do today?” with live vs settled session awareness  
2. **Single-name follow-ups** — “Anything on Google?” with quotes + search grounding  
3. **Normal chat** — lab notes and casual messages should not turn into stock searches  

IDE workspace, character mode, and radar schedulers are **advanced** (off by default). This is not a coding-CLI clone.

Not investment, medical, or legal advice. Conversation content is sent to the LLM/search providers you configure.

---

## Why it works (short)

- **Date anchors** so “today” matches the right US/JP session  
- **Search grounding** with citations instead of inventing headlines  
- **Local storage** for chats/settings (SQLite on your machine)

---

## Quick start

### Option A — Windows desktop launcher

```text
1. Clone or unzip the repo
2. Double-click start_kairi.bat
3. Browser opens http://127.0.0.1:8000/
4. Paste your DeepSeek API key in the first-run wizard
5. Ask: How did the US market do today?
```

If the zip/build includes `runtime\python`, no system Python install is required.  
Builders: `scripts/prepare_embedded_python.ps1` bundles a portable Python runtime.

**Updating a zip install:** keep `backend/storage` (chats + settings). See [`scripts/UPGRADE.txt`](scripts/UPGRADE.txt) and `scripts/backup_storage.bat`. Settings → Language → Backup downloads a zip without wiping the install.

### Option B — Dev servers

**Backend**

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# set DEEPSEEK_API_KEY (env or Settings UI)
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**Frontend**

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

### Minimum config

| Item | Value |
|------|--------|
| LLM key | `DEEPSEEK_API_KEY` (or Settings → API Keys) |
| Models | DeepSeek defaults in `backend/storage/settings.example.json` |
| Search (optional) | `BRAVE_API_KEY` |

Default UI/locale for public builds: **English**.

**Reply language:** the model follows **Settings → Language (locale)**. English locale prefers English answers (and still switches to Japanese when the latest user message is clearly Japanese). If an old local `backend/storage/settings.json` still has `"locale": "ja"`, set Language to English and save—or recreate from `settings.example.json`.

---

## Demo checklist

See [docs/DEMO.md](docs/DEMO.md). Automated gate: `backend/tests/test_demo_sellable_gate.py`.

---

## Advanced (optional)

| Feature | How to enable |
|---------|----------------|
| IDE / Char / Radar UI | Settings → System → Advanced modes |
| Radar/briefing schedulers | `KAIRI_ENABLE_SCHEDULERS=1` |
| API token (LAN) | Settings / `KAIRI_API_TOKEN` |

---

## License

[MIT](LICENSE) for this source repository.

---

## Disclaimer

Kairi is provided as-is. It is not a substitute for professional advice. You are responsible for API usage fees and for how you use market information.
