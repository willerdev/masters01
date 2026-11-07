"use client";

import { FormEvent, useEffect, useState } from "react";
import { PageTitle } from "@/components/Shell";
import { apiJson } from "@/lib/api";

type TelegramStatus = { connected: boolean; chat_id: string; bot_username: string };

function TelegramNotifications() {
  const [status, setStatus] = useState<TelegramStatus | null>(null);
  const [chatId, setChatId] = useState("");
  const [msg, setMsg] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiJson<TelegramStatus>("/api/v1/notifications/telegram")
      .then((body) => {
        setStatus(body);
        if (body.chat_id) setChatId(body.chat_id);
      })
      .catch(() => undefined);
  }, []);

  async function onConnect(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSaving(true);
    setMsg("");
    try {
      await apiJson("/api/v1/notifications/telegram", {
        method: "POST",
        body: JSON.stringify({ chat_id: chatId.trim() }),
      });
      setStatus((prev) => prev ? { ...prev, connected: true, chat_id: chatId.trim() } : prev);
      setMsg("Connected! A confirmation message has been sent to your Telegram.");
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Could not connect Telegram.");
    } finally {
      setSaving(false);
    }
  }

  async function onDisconnect() {
    setSaving(true);
    setMsg("");
    try {
      await apiJson("/api/v1/notifications/telegram", { method: "DELETE" });
      setStatus((prev) => prev ? { ...prev, connected: false, chat_id: "" } : prev);
      setChatId("");
      setMsg("Telegram disconnected.");
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Could not disconnect Telegram.");
    } finally {
      setSaving(false);
    }
  }

  const botLink = status?.bot_username ? `https://t.me/${status.bot_username}` : null;

  return (
    <section>
      <PageTitle
        title="Telegram notifications"
        detail="Connect your personal Telegram to receive trade alerts, risk warnings, and account notifications directly in chat."
      />

      {status?.connected ? (
        <div
          className="flex items-start justify-between gap-4 border border-line rounded p-4 bg-panel"
          style={{ borderColor: "var(--profit)" }}
        >
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <span
                className="pill ok"
                style={{ color: "var(--profit)", background: "color-mix(in srgb, var(--profit) 14%, transparent)" }}
              >
                Connected
              </span>
              {status.bot_username && (
                <span className="text-sm" style={{ color: "var(--muted)" }}>@{status.bot_username}</span>
              )}
            </div>
            <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>
              Chat ID: <span className="num">{status.chat_id}</span>
            </p>
          </div>
          <button className="danger" type="button" onClick={onDisconnect} disabled={saving}>
            Disconnect
          </button>
        </div>
      ) : (
        <form className="flex flex-col gap-3" onSubmit={onConnect} autoComplete="off">
          {botLink ? (
            <div className="border border-line rounded p-3 bg-panel-2 text-sm flex flex-col gap-2">
              <p style={{ color: "var(--ink)" }}>
                <strong>Step 1</strong> — Open the bot and send it any message:
              </p>
              <a
                href={botLink}
                target="_blank"
                rel="noopener noreferrer"
                className="primary"
                style={{ display: "inline-block", borderRadius: 6, padding: "7px 14px", background: "var(--accent)", color: "var(--on-accent)", fontWeight: 600, textDecoration: "none", width: "fit-content" }}
              >
                Open @{status?.bot_username} on Telegram ↗
              </a>
              <p className="mt-1" style={{ color: "var(--ink)" }}>
                <strong>Step 2</strong> — Find your chat ID:
                forward any message from the bot to{" "}
                <a href="https://t.me/userinfobot" target="_blank" rel="noopener noreferrer" style={{ color: "var(--accent)" }}>
                  @userinfobot
                </a>{" "}
                and it will reply with your numeric ID.
              </p>
            </div>
          ) : (
            <div className="border border-line rounded p-3 bg-panel-2 text-sm" style={{ color: "var(--muted)" }}>
              To find your Telegram chat ID, forward any message to{" "}
              <a href="https://t.me/userinfobot" target="_blank" rel="noopener noreferrer" style={{ color: "var(--accent)" }}>
                @userinfobot
              </a>{" "}
              and it will reply with your numeric ID. You must message the platform bot at least once before connecting.
            </div>
          )}

          <label className="text-sm flex flex-col gap-1" style={{ color: "var(--muted)" }}>
            Your Telegram chat ID
            <input
              type="text"
              inputMode="numeric"
              placeholder="e.g. 123456789"
              value={chatId}
              onChange={(e) => setChatId(e.target.value)}
              required
              autoComplete="off"
              className="num"
            />
          </label>
          <button className="primary w-fit" type="submit" disabled={saving || !chatId.trim()}>
            {saving ? "Connecting…" : "Connect Telegram"}
          </button>
        </form>
      )}

      {msg && (
        <p
          className="text-sm mt-3"
          style={{ color: status?.connected && !msg.includes("not") ? "var(--profit)" : "var(--muted)" }}
        >
          {msg}
        </p>
      )}
    </section>
  );
}

export default function SettingsPage() {
  const [message, setMessage] = useState("");
  const [key, setKey] = useState("");
  const [provider, setProvider] = useState("deepseek");
  const [apis, setApis] = useState<{ name: string; connected: boolean }[]>([]);
  const [emailFrom, setEmailFrom] = useState("");
  const [emailReady, setEmailReady] = useState(false);
  const hostedKeyOnly = provider === "deepseek" || provider === "openai";

  function loadApis() {
    apiJson<{ name: string; connected: boolean }[]>("/api/v1/integrations")
      .then(setApis)
      .catch(() => undefined);
  }

  useEffect(() => {
    loadApis();
    apiJson<{ configured: boolean; from: string }>("/api/v1/email")
      .then((email) => {
        setEmailFrom(email.from || "");
        setEmailReady(email.configured);
      })
      .catch(() => undefined);
  }, []);

  async function saveAi(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body: Record<string, unknown> = {
      provider,
      enabled: form.get("enabled") === "on",
      api_key: String(form.get("api_key") || ""),
    };
    if (!hostedKeyOnly) {
      body.model = form.get("model");
      body.base_url = form.get("base_url");
      body.temperature = form.get("temperature");
      body.max_tokens = Number(form.get("max_tokens"));
    }
    await apiJson("/api/v1/ai/config", { method: "PUT", body: JSON.stringify(body) });
    loadApis();
    const saved = provider === "openai"
      ? "OpenAI saved. Paste a new key only when you rotate it. It reads Telegram images and can send images back. DeepSeek still places trades."
      : provider === "deepseek"
        ? "DeepSeek saved. Paste a new key only when you rotate it."
        : "AI provider saved. Analysis cannot change risk limits.";
    setMessage(saved);
  }

  async function saveEmail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const saved = await apiJson<{ configured: boolean; from: string }>("/api/v1/email", {
        method: "PUT",
        body: JSON.stringify({
          api_key: String(form.get("api_key") || ""),
          from_address: String(form.get("from_address") || ""),
        }),
      });
      setEmailFrom(saved.from || "");
      setEmailReady(saved.configured);
      loadApis();
      setMessage("Resend saved. Paste a new key only when you rotate it. Send a test to confirm the from address.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Email settings were not saved");
    }
  }

  async function sendTest() {
    try {
      const sent = await apiJson<{ to: string }>("/api/v1/email/test", { method: "POST" });
      setMessage(`Test sent to ${sent.to}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Test email was not sent");
    }
  }

  async function createKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body = await apiJson<{ api_key: string }>("/api/v1/api-keys", {
      method: "POST",
      body: JSON.stringify({ name: form.get("name"), scopes: ["accounts.read"] }),
    });
    setKey(body.api_key);
  }

  return (
    <div className="grid xl:grid-cols-2 gap-8 max-w-5xl">
      <section className="xl:col-span-2 max-w-xl">
        <PageTitle title="Connected APIs" detail="Each saved key is checked with its provider." />
        <ul className="border border-line rounded bg-panel">
          {apis.map((api) => (
            <li key={api.name} className="flex items-center justify-between gap-3 px-3 py-2 border-b border-line last:border-b-0">
              <span>{api.name}</span>
              <span className={api.connected ? "text-profit" : "text-loss"}>{api.connected ? "Connected" : "Not connected"}</span>
            </li>
          ))}
        </ul>
      </section>
      <section>
        <PageTitle title="AI settings" detail="Optional. Stop-loss, daily loss, drawdown, trade count, exposure, and emergency stop never call the provider." />
        <form className="flex flex-col gap-3" autoComplete="off" onSubmit={saveAi}>
          <select name="provider" value={provider} onChange={(event) => setProvider(event.target.value)}>
            <option value="deepseek">DeepSeek</option>
            <option value="openai">OpenAI</option>
            <option value="gemini">Gemini</option>
            <option value="anthropic">Anthropic</option>
            <option value="local">Local OpenAI-compatible</option>
          </select>
          {provider === "deepseek" ? (
            <p className="text-sm">DeepSeek gives you one API key. The desk uses deepseek-chat on the official host.</p>
          ) : provider === "openai" ? (
            <p className="text-sm">OpenAI gives you one API key. The desk uses it on the official host to read images you send on Telegram and to create images it sends back.</p>
          ) : (
            <>
              <input name="model" autoComplete="off" placeholder="Model" />
              <input name="base_url" autoComplete="off" placeholder="Base URL for a local or custom endpoint" />
              <input name="temperature" type="number" step="0.1" defaultValue="0.2" />
              <input name="max_tokens" type="number" defaultValue="800" />
            </>
          )}
          <input name="api_key" type="password" autoComplete="off" placeholder={provider === "openai" ? "OpenAI API key" : hostedKeyOnly ? "DeepSeek API key" : "API key"} />
          {provider === "openai" ? null : (
            <label className="text-sm flex gap-2 items-center"><input className="w-auto" type="checkbox" name="enabled" defaultChecked={hostedKeyOnly} /> Enable AI</label>
          )}
          <button className="primary" type="submit">Save provider</button>
        </form>
      </section>
      <section>
        <PageTitle title="Email" detail="Resend sends password resets and alert emails. The from address must use a domain you verified in Resend." />
        <form className="flex flex-col gap-3" autoComplete="off" onSubmit={saveEmail}>
          <input name="from_address" autoComplete="off" placeholder="TradeGuard <alerts@yourdomain.com>" value={emailFrom} onChange={(event) => setEmailFrom(event.target.value)} />
          <input name="api_key" type="password" autoComplete="off" placeholder={emailReady ? "Key saved. Paste a new one only to replace it." : "Resend API key"} />
          <button className="primary" type="submit">Save email</button>
        </form>
        <button className="ghost mt-3" type="button" onClick={sendTest}>Send test to my email</button>
      </section>
      <section>
        <PageTitle title="API keys" detail="The raw key is shown once." />
        <form className="flex flex-col gap-3" onSubmit={createKey}>
          <input name="name" placeholder="Key name" required />
          <button className="primary" type="submit">Create key</button>
        </form>
        {key ? <p className="num break-all mt-3 text-sm">{key}</p> : null}
      </section>
      <section className="xl:col-span-2 max-w-xl">
        <TelegramNotifications />
      </section>
      {message ? <p className="text-sm xl:col-span-2">{message}</p> : null}
    </div>
  );
}
