"use client";
import { useEffect } from "react";
import { token } from "@/lib/api";

// Google sign-in lands here with #token=… (fragment: never sent to a server or logged).
export default function OAuthCallback() {
  useEffect(() => {
    const t = new URLSearchParams(window.location.hash.slice(1)).get("token");
    if (t) {
      token.set(t);
      window.history.replaceState(null, "", "/auth/callback"); // drop the token from the address bar
      window.location.replace("/dashboard");
    } else {
      window.location.replace("/login?error=invalid_state");
    }
  }, []);
  return <p className="p-8 text-sm text-slate-500">Signing you in…</p>;
}
