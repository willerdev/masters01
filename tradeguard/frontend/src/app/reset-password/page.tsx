"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { apiJson } from "@/lib/api";
import { AuthCard } from "../login/page";

export default function ResetPage() {
  const router = useRouter();
  const [error, setError] = useState("");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await apiJson("/api/v1/auth/reset-password", {
        method: "POST",
        body: JSON.stringify({ token: form.get("token"), password: form.get("password") }),
      });
      router.push("/login");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reset failed");
    }
  }

  return (
    <AuthCard title="Choose a new password" error={error}>
      <form className="flex flex-col gap-3" onSubmit={onSubmit}>
        <input name="token" placeholder="Reset token" required />
        <input name="password" type="password" placeholder="New password" required />
        <button className="primary" type="submit">Update password</button>
      </form>
    </AuthCard>
  );
}
