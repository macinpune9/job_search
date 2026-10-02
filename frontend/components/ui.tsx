"use client";
import React from "react";
import { STATUS_LABEL } from "@/lib/api";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

export function Card({ title, actions, children, className }: { title?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={cx("rounded-xl border border-slate-200 bg-white shadow-sm", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      <div className="flex gap-2">{actions}</div>
    </div>
  );
}

type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "ghost"; busy?: boolean };
export function Button({ variant = "primary", busy, className, children, disabled, ...p }: BtnProps) {
  const v = {
    primary: "bg-brand-600 text-white hover:bg-brand-700",
    secondary: "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50",
    danger: "bg-red-600 text-white hover:bg-red-700",
    ghost: "text-slate-600 hover:bg-slate-100",
  }[variant];
  return (
    <button {...p} disabled={disabled || busy}
      className={cx("inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 disabled:cursor-not-allowed disabled:opacity-50", v, className)}>
      {busy && <Spinner className="h-4 w-4" />}
      {children}
    </button>
  );
}

export const Spinner = ({ className = "h-5 w-5" }: { className?: string }) => (
  <svg className={cx("animate-spin text-current", className)} viewBox="0 0 24 24" fill="none" role="status" aria-label="Loading">
    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" className="opacity-25" />
    <path d="M4 12a8 8 0 018-8" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
  </svg>
);

export const Loading = () => <div className="flex justify-center p-10 text-slate-400"><Spinner className="h-7 w-7" /></div>;
export const ErrorBox = ({ message }: { message?: string | null }) =>
  message ? <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{message}</div> : null;
export const Notice = ({ children, tone = "info" }: { children: React.ReactNode; tone?: "info" | "warn" | "ok" }) => (
  <div className={cx("rounded-lg border px-3 py-2 text-sm", tone === "info" && "border-blue-200 bg-blue-50 text-blue-800", tone === "warn" && "border-amber-200 bg-amber-50 text-amber-800", tone === "ok" && "border-emerald-200 bg-emerald-50 text-emerald-800")}>{children}</div>
);
export const Empty = ({ title, hint, action }: { title: string; hint?: string; action?: React.ReactNode }) => (
  <div className="rounded-xl border border-dashed border-slate-300 p-10 text-center">
    <p className="font-medium text-slate-700">{title}</p>
    {hint && <p className="mt-1 text-sm text-slate-500">{hint}</p>}
    {action && <div className="mt-4">{action}</div>}
  </div>
);

const TONE: Record<string, string> = {
  submitted: "bg-emerald-100 text-emerald-800", interview: "bg-emerald-100 text-emerald-800", offer_received: "bg-emerald-100 text-emerald-800",
  ready_to_apply: "bg-blue-100 text-blue-800", awaiting_user_approval: "bg-indigo-100 text-indigo-800", resume_ready_for_review: "bg-amber-100 text-amber-800",
  manual_application_required: "bg-amber-100 text-amber-800", submission_confirmation_pending: "bg-amber-100 text-amber-800",
  application_failed: "bg-red-100 text-red-700", rejected: "bg-red-100 text-red-700", closed_or_expired: "bg-slate-200 text-slate-600", withdrawn: "bg-slate-200 text-slate-600",
};
export const StatusBadge = ({ status }: { status: string }) => (
  <span className={cx("inline-block whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium", TONE[status] || "bg-slate-100 text-slate-700")}>{STATUS_LABEL[status] || status}</span>
);
export const ScoreBadge = ({ score }: { score?: number | null }) => {
  if (score == null) return <span className="text-slate-400">—</span>;
  const c = score >= 70 ? "bg-emerald-100 text-emerald-800" : score >= 50 ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-600";
  return <span className={cx("inline-block rounded-full px-2 py-0.5 text-xs font-semibold", c)}>{Math.round(score)}</span>;
};

export function Field({ label, hint, error, children, htmlFor }: { label: string; hint?: string; error?: string; children: React.ReactNode; htmlFor?: string }) {
  return (
    <div className="space-y-1">
      <label htmlFor={htmlFor} className="block text-sm font-medium text-slate-700">{label}</label>
      {children}
      {hint && !error && <p className="text-xs text-slate-500">{hint}</p>}
      {error && <p className="text-xs text-red-600" role="alert">{error}</p>}
    </div>
  );
}
export const inputCls = "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100";
export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...p }, ref) {
  return <input ref={ref} {...p} className={cx(inputCls, className)} />;
});
export const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, ...p }, ref) {
  return <select ref={ref} {...p} className={cx(inputCls, className)} />;
});
export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...p }, ref) {
  return <textarea ref={ref} {...p} className={cx(inputCls, className)} />;
});

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="flex items-center justify-between pt-3 text-sm text-slate-600">
      <span>{total} result{total === 1 ? "" : "s"}</span>
      <div className="flex items-center gap-2">
        <Button variant="secondary" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</Button>
        <span>Page {page} of {pages}</span>
        <Button variant="secondary" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</Button>
      </div>
    </div>
  );
}

export function Table({ children }: { children: React.ReactNode }) {
  return <div className="overflow-x-auto rounded-lg border border-slate-200"><table className="min-w-full divide-y divide-slate-200 text-sm">{children}</table></div>;
}
export const Th = ({ children }: { children?: React.ReactNode }) => <th scope="col" className="whitespace-nowrap bg-slate-50 px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">{children}</th>;
export const Td = ({ children, className }: { children?: React.ReactNode; className?: string }) => <td className={cx("px-3 py-2 align-top text-slate-700", className)}>{children}</td>;

export function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-slate-900">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

export function Chip({ children, onRemove, tone = "slate" }: { children: React.ReactNode; onRemove?: () => void; tone?: "slate" | "green" | "red" | "amber" }) {
  const t = { slate: "bg-slate-100 text-slate-700", green: "bg-emerald-100 text-emerald-800", red: "bg-red-100 text-red-700", amber: "bg-amber-100 text-amber-800" }[tone];
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium", t)}>
      {children}
      {onRemove && <button type="button" onClick={onRemove} aria-label="Remove" className="ml-0.5 opacity-60 hover:opacity-100">×</button>}
    </span>
  );
}

export const useToast = () => {
  const [msg, setMsg] = React.useState<{ text: string; tone: "ok" | "err" } | null>(null);
  React.useEffect(() => { if (msg) { const t = setTimeout(() => setMsg(null), 4000); return () => clearTimeout(t); } }, [msg]);
  const node = msg ? <div role="status" className={cx("fixed bottom-4 right-4 z-50 max-w-sm rounded-lg px-4 py-3 text-sm text-white shadow-lg", msg.tone === "ok" ? "bg-emerald-600" : "bg-red-600")}>{msg.text}</div> : null;
  return { toast: (text: string, tone: "ok" | "err" = "ok") => setMsg({ text, tone }), node };
};
