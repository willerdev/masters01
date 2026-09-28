# Security

- Passwords are hashed with Argon2id. Minimum length is 12, with a letter and a digit.
- Access JWTs expire in 15 minutes, are signed only with HS256, and carry a session id. Logout revokes that session, so the access token stops working immediately. Authorization uses roles stored in the database, not the role list inside the token.
- Login, registration, and password-reset requests are rate limited per client address.
- Webhook API keys and signatures are compared in constant time. A nonce is recorded only after the signature matches, so an unsigned request cannot probe which nonces were used.
- Cookie mutations from the browser must send `X-Tradeguard-Request: 1`.
- Roles map to explicit permissions. VIEWER cannot create accounts or run emergency actions. EMERGENCY_STOP requires `emergency.stop` and the typed confirmation `EMERGENCY STOP`.
- Broker passwords, MetaAPI tokens, webhook signing secrets, and AI keys are encrypted with AES-256-GCM. The master key comes from the environment.
- API keys are stored as a prefix plus a hash. The raw value is returned once.
- Webhooks require key, timestamp, nonce, and HMAC over the raw body.
- Audit rows cannot be updated or deleted through the ORM, and PostgreSQL rejects those statements with a trigger. The UI has no audit edit control.
- Logs pass a redaction filter. Do not add print statements for credentials.
- AI output is stored as analysis text. There is no code path from the AI provider to `risk_rules`.
- If the risk function raises, the decision is BLOCK (`ENGINE_FAILURE`). An AI or email outage does not skip that decision.
- Rate limit on webhook ingress is 30 requests per second per token in the API process. A database outage rolls the request back and returns an error instead of acknowledging an event that was not stored.
