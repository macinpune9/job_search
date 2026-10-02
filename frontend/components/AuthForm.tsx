"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { API, api, token } from "@/lib/api";
import { Button, ErrorBox, Field, Input } from "@/components/ui";

const loginSchema = z.object({ email: z.string().email("Enter a valid email"), password: z.string().min(1, "Enter your password") });
const registerSchema = z.object({
  email: z.string().email("Enter a valid email"),
  password: z.string().min(10, "At least 10 characters").regex(/[A-Za-z]/, "Include a letter").regex(/\d/, "Include a digit"),
});

const OAUTH_ERRORS: Record<string, string> = {
  google_not_configured: "Google sign-in is not configured on this server.",
  google_denied: "Google sign-in was cancelled.",
  invalid_state: "Sign-in session expired. Please try again.",
  email_not_verified: "Your Google email address is not verified.",
  account_conflict: "This email is already linked to a different Google account.",
  account_disabled: "This account is disabled.",
};

export default function AuthForm({ mode }: { mode: "login" | "register" }) {
  const isLogin = mode === "login";
  const { register, handleSubmit, formState: { errors } } = useForm<{ email: string; password: string }>({ resolver: zodResolver(isLogin ? loginSchema : registerSchema) });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [google, setGoogle] = useState(false);
  useEffect(() => {
    api<{ google: boolean }>("/api/auth/providers").then((p) => setGoogle(p.google)).catch(() => {});
    const e = new URLSearchParams(window.location.search).get("error");
    if (e) setError(OAUTH_ERRORS[e] || "Google sign-in failed. Please try again.");
  }, []);

  async function login(v: { email: string; password: string }) {
    const r = await api<{ access_token: string }>("/api/auth/login", { body: v });
    token.set(r.access_token);
    window.location.href = "/dashboard";
  }
  const onSubmit = async (v: { email: string; password: string }) => {
    setBusy(true);
    setError(null);
    try {
      if (!isLogin) {
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        await api("/api/auth/register", { body: { ...v, timezone: tz } });
      }
      await login(v);
    } catch (e: any) {
      setError(e.message);
      setBusy(false);
    }
  };
  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={handleSubmit(onSubmit)} className="w-full max-w-sm space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm" noValidate>
        <div>
          <h1 className="text-xl font-semibold text-slate-900">{isLogin ? "Sign in to JobPilot" : "Create your account"}</h1>
          <p className="mt-1 text-sm text-slate-500">Discover jobs, tailor your resume honestly, track every application.</p>
        </div>
        <ErrorBox message={error} />
        <Field label="Email" htmlFor="email" error={errors.email?.message}><Input id="email" type="email" autoComplete="email" {...register("email")} /></Field>
        <Field label="Password" htmlFor="password" error={errors.password?.message} hint={isLogin ? undefined : "10+ characters, with a letter and a digit"}>
          <Input id="password" type="password" autoComplete={isLogin ? "current-password" : "new-password"} {...register("password")} />
        </Field>
        <Button type="submit" busy={busy} className="w-full">{isLogin ? "Sign in" : "Create account"}</Button>
        {google && (
          <>
            <div className="flex items-center gap-3 text-xs text-slate-400"><span className="h-px flex-1 bg-slate-200" />or<span className="h-px flex-1 bg-slate-200" /></div>
            <a href={`${API}/api/auth/google/login`} className="flex w-full items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
              <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true"><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.1C12.4 13.6 17.7 9.5 24 9.5z"/><path fill="#4285F4" d="M46.1 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.4c-.5 2.9-2.2 5.3-4.6 6.9l7.1 5.5c4.3-4 6.8-9.9 6.8-16.9z"/><path fill="#FBBC05" d="M10.5 28.7c-.5-1.4-.8-2.9-.8-4.7s.3-3.3.8-4.7l-7.9-6.1C.9 16.4 0 20.1 0 24s.9 7.6 2.6 10.8l7.9-6.1z"/><path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.1-5.5c-2 1.4-4.9 2.3-8.8 2.3-6.3 0-11.6-4.1-13.5-9.8l-7.9 6.1C6.5 42.6 14.6 48 24 48z"/></svg>
              Continue with Google
            </a>
          </>
        )}
        <p className="text-center text-sm text-slate-500">
          {isLogin ? <>No account? <Link className="text-brand-600 hover:underline" href="/register">Register</Link></> : <>Have an account? <Link className="text-brand-600 hover:underline" href="/login">Sign in</Link></>}
        </p>
      </form>
    </main>
  );
}
