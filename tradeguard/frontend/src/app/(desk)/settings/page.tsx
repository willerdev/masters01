"use client";

import { FormEvent, useEffect, useState } from "react";
import { PageTitle } from "@/components/Shell";
import { apiJson } from "@/lib/api";

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
      {message ? <p className="text-sm xl:col-span-2">{message}</p> : null}
    </div>
  );
}
