"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    router.replace(sessionStorage.getItem("tg_access") ? "/dashboard" : "/login");
  }, [router]);
  return null;
}
