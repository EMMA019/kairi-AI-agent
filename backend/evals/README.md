# Kairi Eval Harness

正規表現パッチやプロンプト変更の回帰を防ぐオフライン評価です。

## 実行

```bash
cd backend
python evals/run_evals.py
```

LLM は呼びません。`mock_executor_output` に fact filter / citation / carryover を通して期待性質を判定します。

## ケース追加

`evals/cases/*.yaml` に事故パターンを追加してください。最低限のフィールド:

- `id` / `description`
- `input` / `history` / `search_results`
- `mock_executor_output`（または `carryover_fixture`）
- `expectations`（`must_not_contain` / `ends_with_terminal` 等）
- `pipeline`: `fact_filters_only` | `carryover_only`
