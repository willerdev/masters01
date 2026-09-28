# User manual

Sign in at the desk. The first local administrator is created from `SEED_ADMIN_EMAIL` when the API starts.

The first time a firm opens the desk, TradeGuard asks for country, language, phone country code, phone number, admin email, and Google Authenticator. Scan the QR code, or open the setup key if you cannot scan. On the same page, connect one account with MetaAPI or with MetaTrader 5 running on this computer. There is no next or previous step. MetaAPI needs a token and account id. TradeGuard looks up the region and reads the account only after the broker connection is live. MetaTrader 5 needs login, password, and server, then reads the rest from the terminal. Saving stays disabled until that check succeeds. Webhook accounts, added later, still need a display name and account number because they have no terminal to read.

After Google Authenticator is enabled, sign-in asks for the 6-digit code before a session is issued.

## Desk

- Dashboard — firm totals, health, and charts.
- Accounts — connect, disconnect, test, monitor, and emergency controls. Emergency actions require the exact confirmation phrase.
- Positions — open tickets, risk, and floating P/L.
- Trades — closed tickets.
- Risk Engine — position simulator and the decision log.
- Risk Rules — per-account limits.
- Alerts — in-app notifications and channel destinations.
- Analytics — combined capital, exposure, drawdown, and shared-currency overlap.
- Reports — daily, weekly, or monthly risk, performance, violation, and behavior reports as PDF, CSV, or JSON.
- AI Copilot — questions answered from account data. Answers label data, calculation, interpretation, and recommendation.
- Webhooks — connection status. Secrets are shown once when the account is created.
- API Keys — create a key. The raw value is shown once.
- Settings — AI provider (OpenAI, Gemini, Anthropic, DeepSeek, or a local model), model, key, temperature, token limit, and the enable switch.
- Audit Logs — append-only. There is no edit control.

## Simulator

Enter balance, risk percent, symbol, entry, stop, and lot. The page returns potential loss, risk percent, suggested size, margin, exposure, and risk/reward. It also shows equity after five losses at that risk percent, a 3% daily loss, and the loss budget at 1% versus 2%.

## Copy monitoring

Create a link with `POST /api/v1/copy-links` naming a master and a follower. A copied order is checked against the follower’s rules before a command is queued. A failed check is stored on the follower and is not executed.
