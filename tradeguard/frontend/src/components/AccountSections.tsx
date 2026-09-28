"use client";

import { useEffect, useState } from "react";
import { apiJson } from "@/lib/api";

export type ConnectionMethod = "metaapi" | "local_mt5" | "webhook";

export type Probe = {
  ok: boolean;
  status: string;
  error_code: string;
  detail: string;
  region: string;
  account: {
    display_name: string;
    account_number: string;
    broker: string;
    server: string;
    currency: string;
    leverage: string;
    equity?: string;
  } | null;
};

export function AccountSections({
  method,
  onMethod,
  allowWebhook,
  onProbe,
}: {
  method: ConnectionMethod;
  onMethod: (method: ConnectionMethod) => void;
  allowWebhook: boolean;
  onProbe: (probe: Probe | null) => void;
}) {
  const [token, setToken] = useState("");
  const [accountId, setAccountId] = useState("");
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [server, setServer] = useState("");
  const [phase, setPhase] = useState<"idle" | "checking" | "done">("idle");
  const [result, setResult] = useState<Probe | null>(null);

  useEffect(() => {
    onProbe(null);
    setResult(null);
    setPhase("idle");
  }, [method, onProbe]);

  useEffect(() => {
    if (method === "webhook") return;
    const credentials = method === "metaapi"
      ? { token: token.trim(), metaapi_account_id: accountId.trim() }
      : { login: login.trim(), password, server: server.trim() };
    const ready = method === "metaapi"
      ? credentials.token.length >= 20 && credentials.metaapi_account_id.length >= 8
      : Boolean(credentials.login && credentials.password && credentials.server);
    if (!ready) {
      setPhase("idle");
      setResult(null);
      onProbe(null);
      return;
    }
    let cancelled = false;
    setPhase("checking");
    setResult(null);
    onProbe(null);
    const handle = window.setTimeout(() => {
      apiJson<Probe>("/api/v1/connections/probe", {
        method: "POST",
        body: JSON.stringify({ connection_method: method, credentials }),
      })
        .then((body) => {
          if (cancelled) return;
          setResult(body);
          setPhase("done");
          onProbe(body.ok ? body : null);
        })
        .catch((err: Error) => {
          if (cancelled) return;
          const failed: Probe = { ok: false, status: "failed", error_code: "probe_failed", detail: err.message, region: "", account: null };
          setResult(failed);
          setPhase("done");
          onProbe(null);
        });
    }, 450);
    return () => {
      cancelled = true;
      window.clearTimeout(handle);
    };
  }, [method, token, accountId, login, password, server, onProbe]);

  return (
    <div className="flex flex-col gap-4">
      <fieldset className="section">
        <legend>1. Connection</legend>
        <div className="grid sm:grid-cols-2 gap-2">
          <label className={`choice ${method === "metaapi" ? "on" : ""}`}>
            <input type="radio" name="connection_method" value="metaapi" checked={method === "metaapi"} onChange={() => onMethod("metaapi")} />
            <span>
              <strong>MetaAPI</strong>
              <span className="block text-xs text-muted">Cloud terminal. The region is read from the token and account id.</span>
            </span>
          </label>
          <label className={`choice ${method === "local_mt5" ? "on" : ""}`}>
            <input type="radio" name="connection_method" value="local_mt5" checked={method === "local_mt5"} onChange={() => onMethod("local_mt5")} />
            <span>
              <strong>MetaTrader 5</strong>
              <span className="block text-xs text-muted">The terminal must be running and logged in on this same computer.</span>
            </span>
          </label>
          {allowWebhook ? (
            <label className={`choice ${method === "webhook" ? "on" : ""}`}>
              <input type="radio" name="connection_method" value="webhook" checked={method === "webhook"} onChange={() => onMethod("webhook")} />
              <span>
                <strong>Webhook</strong>
                <span className="block text-xs text-muted">An Expert Advisor posts events. Credentials are shown once after save.</span>
              </span>
            </label>
          ) : null}
        </div>
      </fieldset>
      <fieldset className="section">
        <legend>2. Credentials</legend>
        {method === "metaapi" ? (
          <div className="grid gap-3">
            <input name="token" type="password" placeholder="MetaAPI token" value={token} onChange={(event) => setToken(event.target.value)} required autoComplete="off" />
            <input name="metaapi_account_id" placeholder="MetaAPI account id" value={accountId} onChange={(event) => setAccountId(event.target.value)} required />
          </div>
        ) : null}
        {method === "local_mt5" ? (
          <div className="grid gap-3">
            <p className="text-sm text-muted">Open MetaTrader 5 on this computer before continuing. Login, password, and server are used only for the live check. Name, account number, broker, currency, and leverage are read from the terminal.</p>
            <input name="login" placeholder="MT5 login" value={login} onChange={(event) => setLogin(event.target.value)} required />
            <input name="mt5_password" type="password" placeholder="MT5 password" value={password} onChange={(event) => setPassword(event.target.value)} required autoComplete="new-password" />
            <input name="server" placeholder="Server" value={server} onChange={(event) => setServer(event.target.value)} required />
          </div>
        ) : null}
        {method === "webhook" ? (
          <div className="grid sm:grid-cols-2 gap-3">
            <p className="text-sm text-muted sm:col-span-2">A webhook has no terminal to read, so the name and account number are entered here. The path, API key, and signing secret are shown once after save.</p>
            <input name="display_name" placeholder="Display name" required />
            <input name="account_number" placeholder="Account number" required />
          </div>
        ) : null}
        {method !== "webhook" && phase === "checking" ? <p className="text-sm text-muted mt-3">Checking the live connection…</p> : null}
        {method !== "webhook" && phase === "done" && result?.ok && result.account ? (
          <div className="mt-3 text-sm">
            <p className="text-profit">Connected{result.region ? ` · ${result.region}` : ""}</p>
            <p className="mt-1">{result.account.display_name} · {result.account.account_number}</p>
            <p className="text-muted">{[result.account.broker, result.account.server, result.account.currency, `1:${result.account.leverage}`].filter(Boolean).join(" · ")}</p>
            {result.account.equity ? <p className="num mt-1">Equity {result.account.equity}</p> : null}
          </div>
        ) : null}
        {method !== "webhook" && phase === "done" && result && !result.ok ? <p className="text-sm text-loss mt-3">{result.detail || "Connection check failed"}</p> : null}
      </fieldset>
    </div>
  );
}

export function accountBody(form: FormData, method: ConnectionMethod, probe: Probe | null) {
  if (method === "webhook") {
    return {
      display_name: form.get("display_name"),
      account_number: form.get("account_number"),
      broker: "",
      server: "",
      connection_method: method,
      currency: "USD",
      leverage: "100",
      trading_day_timezone: "UTC",
    };
  }
  if (!probe?.ok || !probe.account) {
    throw new Error("Wait until the live connection check succeeds");
  }
  const credentials = method === "metaapi"
    ? {
        token: String(form.get("token") || ""),
        metaapi_account_id: String(form.get("metaapi_account_id") || ""),
        region: probe.region,
      }
    : {
        login: String(form.get("login") || ""),
        password: String(form.get("mt5_password") || ""),
        server: String(form.get("server") || probe.account.server),
      };
  return {
    display_name: probe.account.display_name,
    account_number: probe.account.account_number,
    broker: probe.account.broker,
    server: probe.account.server,
    connection_method: method,
    currency: probe.account.currency,
    leverage: probe.account.leverage,
    trading_day_timezone: "UTC",
    credentials,
  };
}
