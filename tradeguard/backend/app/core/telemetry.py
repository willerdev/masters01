from __future__ import annotations

import time
from collections import defaultdict


class Telemetry:
    def __init__(self) -> None:
        self.requests = 0
        self.errors = 0
        self.duration_ms = 0.0
        self.by_path: dict[str, int] = defaultdict(int)
        self.webhooks = 0
        self.decisions = defaultdict(int)

    def observe(self, path: str, status: int, duration_ms: float) -> None:
        self.requests += 1
        self.duration_ms += duration_ms
        self.by_path[path] += 1
        if status >= 500:
            self.errors += 1

    def render(self) -> str:
        avg = 0 if self.requests == 0 else self.duration_ms / self.requests
        lines = [
            "# HELP tradeguard_http_requests_total HTTP requests served",
            "# TYPE tradeguard_http_requests_total counter",
            f"tradeguard_http_requests_total {self.requests}",
            "# HELP tradeguard_http_errors_total HTTP 5xx responses",
            "# TYPE tradeguard_http_errors_total counter",
            f"tradeguard_http_errors_total {self.errors}",
            "# HELP tradeguard_http_duration_ms_avg Mean request duration in milliseconds",
            "# TYPE tradeguard_http_duration_ms_avg gauge",
            f"tradeguard_http_duration_ms_avg {avg:.3f}",
            "# HELP tradeguard_webhook_events_total Accepted webhook events",
            "# TYPE tradeguard_webhook_events_total counter",
            f"tradeguard_webhook_events_total {self.webhooks}",
        ]
        lines.append("# HELP tradeguard_risk_decisions_total Decisions by outcome")
        lines.append("# TYPE tradeguard_risk_decisions_total counter")
        for decision, count in sorted(self.decisions.items()):
            lines.append(f'tradeguard_risk_decisions_total{{decision="{decision}"}} {count}')
        return "\n".join(lines) + "\n"


telemetry = Telemetry()


class RequestTimer:
    def __init__(self) -> None:
        self.started = time.perf_counter()

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self.started) * 1000
