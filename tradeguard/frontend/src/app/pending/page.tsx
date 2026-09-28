"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PortalFrame } from "@/components/PortalFrame";
import { apiJson } from "@/lib/api";

export default function PendingPage() {
  const router = useRouter();
  const [note, setNote] = useState("");
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("pending");

  useEffect(() => {
    apiJson<{ destination: string; application: { kind: string; status: string; review_note: string } | null }>("/api/v1/portal/home")
      .then((home) => {
        if (home.destination === "desk") router.replace("/dashboard");
        if (home.destination === "investor") router.replace("/investor");
        if (home.destination === "trader") router.replace("/trader");
        setKind(home.application?.kind || "");
        setStatus(home.application?.status || "pending");
        setNote(home.application?.review_note || "");
      })
      .catch(() => router.replace("/login"));
  }, [router]);

  return (
    <PortalFrame title="Application">
      <h1 className="text-2xl font-semibold mb-2">{status === "rejected" ? "Application was not approved" : "Waiting for an admin"}</h1>
      <p className="text-sm text-muted">
        {kind === "trader" ? "Your trader application" : "Your investor application"} is {status}. The desk does not open a book or record units until someone approves it.
      </p>
      {note ? <p className="mt-4 text-sm border border-line bg-panel rounded p-3">{note}</p> : null}
    </PortalFrame>
  );
}
