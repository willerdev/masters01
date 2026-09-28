# Architecture

TradeGuard is a risk desk. The deterministic engine decides ALLOW, WARNING, BLOCK, or EMERGENCY_STOP. AI sits beside that path and cannot change a limit or skip a check.

```mermaid
flowchart TD
  event[Market or MT5 event] --> validate[Event validation]
  validate --> state[Account state]
  state --> engine[Risk engine]
  engine --> rules[Risk rules]
  rules --> decision[Decision]
  decision --> action[Action]
  action --> audit[Audit log]
  engine --> ai[AI analysis]
  ai --> audit
```

```mermaid
flowchart LR
  subgraph adapters [MT5 adapters]
    webhook[Webhook]
    metaapi[MetaAPI]
    local[Local terminal]
  end
  adapters --> normalize[Normalized position and quote]
  normalize --> engine[tradeguard_risk]
  engine --> store[(PostgreSQL)]
  store --> desk[Next.js desk]
  redis[(Redis)] --> worker[Celery heartbeat sweep]
```

The risk package has no database or network calls. The API normalizes broker payloads, loads account state, and calls `evaluate_fail_closed`. A raised exception becomes BLOCK with code ENGINE_FAILURE.

Copy monitoring is optional. A master fill that the engine allows or warns on is re-checked against each follower. A follower BLOCK or EMERGENCY_STOP is stored and is not queued for execution.
