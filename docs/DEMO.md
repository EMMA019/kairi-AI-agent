# Demo script

Automated gate: `backend/tests/test_demo_sellable_gate.py`  

Prerequisites: DeepSeek key set, app running at `http://127.0.0.1:8000/`.

## Demo 1 — US market today

**Input:** `How did the US market do today?`

**Pass if:**

- Mentions major indices (Dow / Nasdaq / S&P, etc.)
- Live vs settled / close date matches the session
- No raw tool dump in the chat body (`[Local Tool:]`, search result dumps)

## Demo 2 — Single name

**Input:** `Anything on Google? Did it go up today?`

**Pass if:**

- GOOGL/GOOG price sense (close or live)
- Short “why it moved” / news summary when available
- Works without saying “US market” explicitly
- No tool dump in the body

## Demo 3 — Non-finance paste (must not become stocks)

**Input example:**

```text
I donated blood — what do you think of these lab results?
ALT (GPT)
2026/7/30
RBC 518
```

**Pass if:**

- Does not search ALT as a ticker
- No unsolicited Dow / finance disclaimer spam
- Treats it as a casual/lab chat (not investment advice)

## Demo 4 — No tool dump

Across demos 1–3, the visible answer must not include raw tool/search payloads.

## Recording (optional, ~5 min)

1. Launch `start_kairi.bat`
2. First-run key wizard (mask the key on camera)
3. Demo 1 → Demo 2 → short Demo 3
4. Caption: BYOK · API fees billed by the provider · MIT source on GitHub
