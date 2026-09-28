"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { apiJson } from "@/lib/api";
import { AuthCard } from "../login/page";

export default function ForgotPage() {
  const [message, setMessage] = useState("");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body = await apiJson<{ detail: string }>("/api/v1/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email: form.get("email") }),
    });
    setMessage(body.detail);
  }

  return (
    <AuthCard title="Reset password" error="">
      <form className="flex flex-col gap-3" onSubmit={onSubmit}>
        <input name="email" type="email" placeholder="Email" required />
        <button className="primary" type="submit">Send reset token</button>
      </form>
      {message ? <p className="text-sm mt-3">{message}</p> : null}
      <p className="text-sm text-muted mt-3">If SMTP is configured, the token arrives by email. Use it on the reset page.</p>
      <Link className="text-sm text-muted" href="/reset-password">I have a token</Link>
    </AuthCard>
  );
}
