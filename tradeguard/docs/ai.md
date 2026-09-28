# AI integration

AI is optional. Disable it in Settings and the risk engine keeps enforcing stop-loss, daily loss, drawdown, trade count, exposure, and emergency stop.

## Providers

OpenAI, Gemini, Anthropic, DeepSeek, and a local OpenAI-compatible endpoint. DeepSeek uses `https://api.deepseek.com/v1` and defaults to `deepseek-chat` when the model field is empty. The API key is encrypted with AES-256-GCM. Responses never include the key. Temperature and the maximum token limit are stored with the provider row. AI can be disabled completely.

## Copilot

`POST /api/v1/accounts/{id}/copilot` with `{"question": "..."}`.

The answer always has four parts:

- `data` — figures read from the account
- `calculation` — arithmetic and the latest stored rule hits
- `interpretation` — health reasons, plus provider text only when AI is enabled and responds
- `recommendation` — does not write risk rules

If the provider is down, `ai_used` is false and the measured sections are still returned.

The provider is asked for JSON commentary and is instructed not to propose numeric limit changes. There is no code path from the provider to `risk_rules`.
