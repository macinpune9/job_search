"use client";
import { useCallback, useEffect, useState } from "react";

export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const KEY = "jobpilot.token";

// NOTE: the bearer token lives in localStorage for simplicity. For a hardened deployment put the API behind the
// same origin and switch to an httpOnly session cookie (see docs/security.md).
export const token = {
  get: () => (typeof window === "undefined" ? null : window.localStorage.getItem(KEY)),
  set: (t: string) => window.localStorage.setItem(KEY, t),
  clear: () => window.localStorage.removeItem(KEY),
};

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message);
  }
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const t = token.get();
  if (t) headers.Authorization = `Bearer ${t}`;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, {
      method: opts.method || (opts.body !== undefined || opts.form ? "POST" : "GET"),
      headers,
      body: opts.form ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined),
    });
  } catch {
    throw new ApiError(0, "network", "Cannot reach the API. Is the backend running?");
  }
  if (res.status === 401 && !path.startsWith("/api/auth/")) {
    token.clear();
    if (typeof window !== "undefined") window.location.href = "/login";
  }
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("json") ? await res.json() : await res.text();
  if (!res.ok) {
    const e = (data as any)?.error;
    let msg = e?.message || (typeof data === "string" ? data : "Request failed");
    if (Array.isArray(e?.details)) msg += ": " + e.details.map((d: any) => `${d.field} ${d.message}`).join("; ");
    throw new ApiError(res.status, e?.code || "error", typeof msg === "string" ? msg : JSON.stringify(msg), e?.details);
  }
  return data as T;
}

export function useApi<T = any>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!!path);
  const reload = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try {
      setData(await api<T>(path));
      setError(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  useEffect(() => {
    reload();
  }, [reload]);
  return { data, error, loading, reload, setData };
}

export async function download(path: string, filename: string) {
  const res = await fetch(`${API}${path}`, { headers: { Authorization: `Bearer ${token.get()}` } });
  if (!res.ok) throw new Error("Download failed");
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export async function openSigned(linkPath: string) {
  const r = await api<{ url: string }>(linkPath);
  const res = await fetch(`${API}${r.url}`);
  if (!res.ok) throw new Error("Link expired");
  const cd = res.headers.get("content-disposition") || "";
  const name = /filename="([^"]+)"/.exec(cd)?.[1] || "download";
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export const fmtDate = (s?: string | null, tz?: string) =>
  s ? new Date(s).toLocaleString(undefined, { timeZone: tz, dateStyle: "medium", timeStyle: "short" }) : "—";
export const fmtDay = (s?: string | null) => (s ? new Date(s).toLocaleDateString(undefined, { dateStyle: "medium" }) : "—");

export const STATUS_LABEL: Record<string, string> = {
  newly_discovered: "Newly discovered", needs_review: "Needs review", resume_generation_pending: "Resume pending",
  resume_ready_for_review: "Resume needs fixes", ready_to_apply: "Ready to apply", awaiting_user_approval: "Awaiting approval",
  application_in_progress: "In progress", submitted: "Submitted", submission_confirmation_pending: "Confirmation pending",
  manual_application_required: "Manual application", application_failed: "Failed", closed_or_expired: "Closed",
  rejected: "Rejected", interview: "Interview", offer_received: "Offer", withdrawn: "Withdrawn",
};
