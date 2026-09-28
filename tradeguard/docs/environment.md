# Environment variables

Copy `.env.example` to `.env`. Never commit `.env`.

| Variable | Purpose |
| --- | --- |
| ENVIRONMENT | `development`, `test`, or `production`. Production refuses the published local master key and the password `LocalAdmin12!`. |
| DATABASE_URL | SQLAlchemy URL. Use the `postgresql+psycopg` driver. |
| REDIS_URL | Celery broker and result backend. |
| JWT_SECRET | HMAC secret for access tokens. Use a long random value. |
| MASTER_KEY | Base64-encoded 32-byte AES-256-GCM key for broker and AI secrets. |
| COOKIE_SECURE | `true` behind HTTPS. |
| CORS_ORIGINS | Comma-separated browser origins. |
| ACCESS token lifetime | `ACCESS_TOKEN_MINUTES` (default 15), `REFRESH_TOKEN_DAYS` (default 14). |
| SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM, SMTP_TLS | Outbound email. Empty host records deliveries as `skipped_unconfigured`. |
| TELEGRAM_BOT_TOKEN | Enables the Telegram channel. Chat id is the channel destination. |
| TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER | Enables SMS. |
| METAAPI_REGION | Default MetaAPI region, for example `new-york`. |
| PUBLIC_BASE_URL | Public API origin used in NOWPayments and Cryptomus callback URLs. |
| SEED_ADMIN_EMAIL, SEED_ADMIN_PASSWORD, SEED_ADMIN_NAME | First super admin, created once. |
| SEED_SAMPLE_DATA | `true` loads a labeled sample book for an empty local desk. |
| NEXT_PUBLIC_API_URL | Browser-visible API origin. |

Generate a master key:

```bash
python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"
```
