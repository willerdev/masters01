# Backup and recovery

## What to back up

- PostgreSQL, including `audit_logs`. That table is the decision history. Take a base backup and archive WAL. Restore it once before calling the deploy finished.
- The environment file: `MASTER_KEY`, `JWT_SECRET`, SMTP, and provider tokens. Store it outside the database backup. Losing `MASTER_KEY` makes encrypted broker and AI secrets unreadable.
- Redis is a Celery broker. It is not the ledger. Losing it delays the heartbeat sweep. The API process also sweeps heartbeats.

## Failures

| Failure | What still works | What to do |
| --- | --- | --- |
| API process down | PostgreSQL keeps accepted events. New webhooks fail closed and are not acknowledged. | Restart the API. Replay from the bridge only for events that did not receive 202. |
| MT5 disconnect | Last account state remains. Health becomes CRITICAL with CONNECTION_DOWN after the heartbeat window. New-trade checks use the last stored state. | Restore the terminal, MetaAPI token, or webhook heartbeats. |
| Redis down | Webhook decisions still commit to PostgreSQL. Celery beat pauses. | Restore Redis. The API sweep continues disconnect detection. |
| AI down | Every hard limit still runs. Copilot returns measurements and says the provider did not respond. | Leave AI disabled or restore the key. |
| Database unavailable | `/ready` returns 503. The API does not acknowledge a webhook it could not store. | Restore PostgreSQL from the base backup and WAL, then start the API. |

Audit rows cannot be updated or deleted through the application or the PostgreSQL trigger. Include them in every backup.
