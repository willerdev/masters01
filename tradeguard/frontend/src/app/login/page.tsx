"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { apiJson, saveSession } from "@/lib/api";
import { homeFor } from "@/components/Shell";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [mfaToken, setMfaToken] = useState("");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      if (mfaToken) {
        const body = await apiJson<{ access_token: string }>("/api/v1/auth/mfa", {
          method: "POST",
          body: JSON.stringify({ mfa_token: mfaToken, code: form.get("code") }),
        });
        saveSession(body.access_token);
        router.push("/dashboard");
        return;
      }
      const body = await apiJson<{ access_token?: string; mfa_required?: boolean; mfa_token?: string; user?: { roles: string[] } }>("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ email: form.get("email"), password: form.get("password") }),
      });
      if (body.mfa_required && body.mfa_token) {
        setMfaToken(body.mfa_token);
        return;
      }
      if (body.access_token) saveSession(body.access_token);
      router.push(homeFor(body.user?.roles || []));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    }
  }

  return (
    <AuthCard title="Sign in" error={error}>
      <form className="flex flex-col gap-3" onSubmit={onSubmit}>
        {mfaToken ? (
          <input name="code" inputMode="numeric" autoComplete="one-time-code" placeholder="Google Authenticator code" required />
        ) : (
          <>
            <input name="email" type="email" placeholder="Email" required />
            <input name="password" type="password" placeholder="Password" required />
          </>
        )}
        <button className="primary" type="submit">{mfaToken ? "Confirm code" : "Enter desk"}</button>
      </form>
      <div className="text-sm text-muted mt-4 flex flex-wrap gap-3 justify-between">
        <Link href="/register">Create a firm</Link>
        <Link href="/join">Apply to join</Link>
        <Link href="/forgot-password">Reset password</Link>
        <Link href="/account-recovery">Lost the account</Link>
      </div>
    </AuthCard>
  );
}

export function AuthCard({ title, error, children }: { title: string; error?: string; children: React.ReactNode }) {
  return (
    <div className="min-h-screen grid place-items-center px-4">
      <div className="w-full max-w-md bg-panel border border-line rounded-lg p-6">
        <div className="text-xs tracking-[0.18em] text-muted">TRADEGUARD</div>
        <h1 className="text-2xl font-semibold mb-4">{title}</h1>
        {error ? <p className="text-loss text-sm mb-3">{error}</p> : null}
        {children}
      </div>
    </div>
  );
}
