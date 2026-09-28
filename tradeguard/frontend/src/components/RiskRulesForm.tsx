"use client";

import { FormEvent, useEffect, useState } from "react";
import { apiJson } from "@/lib/api";

const FIELDS: { key: string; label: string; step: string; kind: "number" | "bool"; detail: string }[] = [
  { key: "risk_per_trade_pct", label: "Risk per trade %", step: "0.01", kind: "number", detail: "Blocks a new order when the loss at the stop is above this share of equity." },
  { key: "max_daily_loss_pct", label: "Max daily loss %", step: "0.01", kind: "number", detail: "Stops new trades when today's loss reaches this percent of the day's starting equity." },
  { key: "max_total_drawdown_pct", label: "Max total drawdown %", step: "0.01", kind: "number", detail: "Stops new trades when equity falls this far from the peak." },
  { key: "max_trades_per_day", label: "Max trades per day", step: "1", kind: "number", detail: "Blocks the next entry after this many trades in the day." },
  { key: "max_open_positions", label: "Max open positions", step: "1", kind: "number", detail: "Blocks a new trade when this many positions are already open." },
  { key: "max_lot", label: "Max lot", step: "0.01", kind: "number", detail: "Blocks an order larger than this lot size." },
  { key: "max_consecutive_losses", label: "Max consecutive losses", step: "1", kind: "number", detail: "Blocks the next trade after this many losing closes in a row." },
  { key: "min_minutes_between_trades", label: "Minimum minutes between trades", step: "1", kind: "number", detail: "Blocks a new entry until this many minutes have passed since the last one." },
  { key: "max_exposure_pct", label: "Max exposure %", step: "0.01", kind: "number", detail: "Blocks a new trade when open exposure is above this percent of equity. Zero also leaves it off." },
  { key: "allow_trading", label: "Allow trading", step: "", kind: "bool", detail: "When this rule is on and Allow trading is unchecked, new trades are blocked." },
];

type RulesPayload = Record<string, string | boolean | Record<string, boolean> | null> & { enabled?: Record<string, boolean> };

export function RiskRulesForm({ accountId }: { accountId: string }) {
  const [values, setValues] = useState<Record<string, string | boolean>>({});
  const [enabled, setEnabled] = useState<Record<string, boolean>>({});
  const [message, setMessage] = useState("");

  useEffect(() => {
    apiJson<RulesPayload>(`/api/v1/accounts/${accountId}/risk-rules`).then((payload) => {
      const next: Record<string, string | boolean> = {};
      for (const field of FIELDS) {
        const raw = payload[field.key];
        next[field.key] = field.kind === "bool" ? raw !== false : raw == null ? "" : String(raw);
      }
      setValues(next);
      setEnabled(payload.enabled || {});
    }).catch((err: unknown) => {
      setMessage(err instanceof Error ? err.message : "Rules could not be loaded");
    });
  }, [accountId]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body: Record<string, string | boolean | Record<string, boolean>> = { enabled: {} };
    const flags: Record<string, boolean> = {};
    for (const field of FIELDS) {
      body[field.key] = field.kind === "bool" ? values[field.key] === true : String(values[field.key] ?? "");
      flags[field.key] = enabled[field.key] !== false;
    }
    body.enabled = flags;
    try {
      const saved = await apiJson<RulesPayload>(`/api/v1/accounts/${accountId}/risk-rules`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
      const next: Record<string, string | boolean> = {};
      for (const field of FIELDS) {
        const raw = saved[field.key];
        next[field.key] = field.kind === "bool" ? raw !== false : raw == null ? "" : String(raw);
      }
      setValues(next);
      setEnabled(saved.enabled || {});
      setMessage("Rules saved. A rule that is off is not used on the next order.");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Save failed");
    }
  }

  return (
    <form className="flex flex-col gap-3 max-w-2xl" onSubmit={onSubmit}>
      {FIELDS.map((field) => {
        const used = enabled[field.key] !== false;
        return (
          <div key={field.key} className="border border-line rounded bg-panel px-3 py-3">
            <label className="flex items-center gap-2 text-sm">
              <input
                className="w-auto"
                type="checkbox"
                checked={used}
                onChange={(event) => setEnabled((current) => ({ ...current, [field.key]: event.target.checked }))}
              />
              <span className="font-medium">{field.label}</span>
            </label>
            <p className="text-xs text-muted mt-1">{field.detail}</p>
            {field.kind === "number" ? (
              <input
                className="mt-2"
                type="number"
                step={field.step}
                value={String(values[field.key] ?? "")}
                disabled={!used}
                onChange={(event) => setValues((current) => ({ ...current, [field.key]: event.target.value }))}
              />
            ) : (
              <label className="flex items-center gap-2 text-sm mt-2">
                <input
                  className="w-auto"
                  type="checkbox"
                  checked={values[field.key] !== false}
                  disabled={!used}
                  onChange={(event) => setValues((current) => ({ ...current, [field.key]: event.target.checked }))}
                />
                Allow trading
              </label>
            )}
          </div>
        );
      })}
      <button className="primary" type="submit">Save rules</button>
      {message ? <p className="text-sm">{message}</p> : null}
    </form>
  );
}
