"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, clearSession } from "@/lib/api";

export function PortalFrame({ title, children }: { title: string; children: React.ReactNode }) {
  const router = useRouter();
  const [email, setEmail] = useState("");

  useEffect(() => {
    api("/api/v1/portal/home")
      .then(async (response) => {
        if (!response.ok) {
          router.replace("/login");
          return;
        }
        const body = await response.json();
        setEmail(body.email || "");
      })
      .catch(() => router.replace("/login"));
  }, [router]);

  async function logout() {
    await api("/api/v1/auth/logout", { method: "POST" });
    clearSession();
    router.replace("/login");
  }

  return (
    <div className="min-h-screen">
      <header className="h-[52px] bg-panel border-b border-line px-5 flex items-center justify-between">
        <div className="font-semibold">{title}</div>
        <div className="flex items-center gap-3 text-sm text-muted">
          <span>{email}</span>
          <button className="ghost" type="button" onClick={logout}>Log out</button>
        </div>
      </header>
      <main className="max-w-4xl mx-auto p-6">{children}</main>
    </div>
  );
}
