"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { apiJson, saveSession } from "@/lib/api";
import { AuthCard } from "../login/page";

export default function RegisterPage() {
  const router = useRouter();
  const [error, setError] = useState("");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const body = await apiJson<{ access_token: string }>("/api/v1/auth/register", {
        method: "POST",
        body: JSON.stringify({
          email: form.get("email"),
          password: form.get("password"),
          full_name: form.get("full_name"),
          organization_name: form.get("organization_name"),
        }),
      });
      saveSession(body.access_token);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    }
  }

  return (
    <AuthCard title="Create a firm" error={error}>
      <form className="flex flex-col gap-3" onSubmit={onSubmit}>
        <input name="organization_name" placeholder="Organization" required />
        <input name="full_name" placeholder="Your name" required />
        <input name="email" type="email" placeholder="Email" required />
        <input name="password" type="password" placeholder="Password, 12+ chars" required />
        <button className="primary" type="submit">Create super admin</button>
      </form>
      <Link className="text-sm text-muted mt-4 inline-block" href="/login">Already registered</Link>
    </AuthCard>
  );
}
