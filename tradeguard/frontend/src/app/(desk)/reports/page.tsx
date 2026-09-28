"use client";

import { FormEvent, useState } from "react";
import { PageTitle } from "@/components/Shell";
import { api, apiJson } from "@/lib/api";

export default function ReportsPage() {
  const [preview, setPreview] = useState("");
  const [error, setError] = useState("");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const period = String(form.get("period"));
    const kind = String(form.get("kind"));
    const format = String(form.get("format"));
    const path = `/api/v1/reports?period=${period}&kind=${kind}&format=${format}`;
    try {
      if (format === "json") {
        const body = await apiJson<{ accounts: unknown[] }>(path);
        setPreview(JSON.stringify(body.accounts, null, 2));
        return;
      }
      const response = await api(path);
      if (!response.ok) throw new Error("Report failed");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `tradeguard-${kind}-${period}.${format}`;
      link.click();
      URL.revokeObjectURL(url);
      setPreview(`Downloaded ${format.toUpperCase()} report.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Report failed");
    }
  }

  return (
    <div>
      <PageTitle title="Reports" detail="Daily, weekly, and monthly risk, performance, violation, and behavior reports." />
      <form className="flex flex-wrap gap-2 mb-4" onSubmit={onSubmit}>
        <select name="period" defaultValue="daily"><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option></select>
        <select name="kind" defaultValue="risk">
          <option value="risk">Risk</option>
          <option value="performance">Performance</option>
          <option value="violations">Violations</option>
          <option value="behavior">Behavior</option>
        </select>
        <select name="format" defaultValue="pdf"><option value="pdf">PDF</option><option value="csv">CSV</option><option value="json">JSON</option></select>
        <button className="primary" type="submit">Generate</button>
      </form>
      {error ? <p className="text-loss">{error}</p> : null}
      {preview ? <pre className="text-xs whitespace-pre-wrap bg-panel border border-line p-3">{preview}</pre> : null}
    </div>
  );
}
