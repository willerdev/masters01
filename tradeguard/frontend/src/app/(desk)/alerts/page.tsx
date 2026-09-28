"use client";

import { useEffect, useState } from "react";
import { PageTitle } from "@/components/Shell";
import { apiJson } from "@/lib/api";

type Alert = { id: string; type: string; severity: string; title: string; body: string; created_at: string };
type Note = { id: string; channel: string; title: string; status: string; read_at: string | null };

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [notes, setNotes] = useState<Note[]>([]);
  const [message, setMessage] = useState("");

  useEffect(() => {
    Promise.all([apiJson<Alert[]>("/api/v1/alerts"), apiJson<Note[]>("/api/v1/notifications")]).then(([a, n]) => {
      setAlerts(a);
      setNotes(n);
    });
  }, []);

  async function saveChannel(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await apiJson("/api/v1/alert-channels", {
      method: "PUT",
      body: JSON.stringify({
        channel: form.get("channel"),
        enabled: form.get("enabled") === "on",
        destination: form.get("destination"),
        secret: form.get("secret"),
      }),
    });
    setMessage("Channel saved. Email sends after Resend is saved on Settings.");
  }

  return (
    <div>
      <PageTitle title="Alerts" detail="In-app notifications are always recorded. External channels send when configured." />
      <form className="grid md:grid-cols-4 gap-2 mb-6 max-w-4xl" onSubmit={saveChannel}>
        <select name="channel" defaultValue="email">
          <option value="email">Email</option>
          <option value="webhook">Webhook</option>
          <option value="telegram">Telegram</option>
          <option value="sms">SMS</option>
        </select>
        <input name="destination" placeholder="Address, URL, chat id, or phone" />
        <input name="secret" placeholder="Webhook signing secret" />
        <label className="flex items-center gap-2 text-sm"><input className="w-auto" type="checkbox" name="enabled" defaultChecked /> Enabled</label>
        <button className="primary" type="submit">Save channel</button>
      </form>
      {message ? <p className="text-sm mb-4">{message}</p> : null}
      <div className="grid xl:grid-cols-2 gap-4">
        <section>
          <h2 className="mb-2">Alert events</h2>
          {alerts.map((alert) => (
            <article key={alert.id} className="border border-line bg-panel rounded mb-2 p-3">
              <div className="text-xs text-muted">{alert.severity} · {alert.type}</div>
              <div>{alert.title}</div>
              <p className="text-sm text-muted">{alert.body}</p>
            </article>
          ))}
        </section>
        <section>
          <h2 className="mb-2">Your notifications</h2>
          {notes.map((note) => (
            <article key={note.id} className="border border-line bg-panel rounded mb-2 p-3 text-sm">
              <div className="text-muted">{note.channel} · {note.status}</div>
              <div>{note.title}</div>
            </article>
          ))}
        </section>
      </div>
    </div>
  );
}
