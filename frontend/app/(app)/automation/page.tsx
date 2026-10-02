"use client";
import { useEffect, useState } from "react";
import { api, useApi } from "@/lib/api";
import { Button, Card, ErrorBox, Field, Input, Loading, Notice, PageHeader, useToast } from "@/components/ui";

const MODES = [
  ["discovery_only", "Discovery only", "Find and score jobs. Nothing is prepared or submitted."],
  ["prepare_for_review", "Prepare applications for review (default)", "Generate validated tailored resumes and application packages. You approve and submit."],
  ["fill_and_request_approval", "Fill supported forms and request approval", "Reserved for supported employer forms. Not implemented yet: behaves like “prepare for review”."],
  ["auto_submit_authorized", "Submit automatically to explicitly authorized integrations", "Only for integrations you've authorized. Never covers legal attestations, demographic, salary or eligibility questions."],
];

export default function Automation() {
  const { data, error, loading, reload } = useApi<any>("/api/automation-settings");
  const [f, setF] = useState<any>(null);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const { toast, node } = useToast();
  useEffect(() => { if (data) setF(data); }, [data]);
  if (loading || !f) return <Loading />;
  async function save(patch: any) {
    setBusy(true);
    try { await api("/api/automation-settings", { method: "PATCH", body: patch }); toast("Saved"); await reload(); } catch (e: any) { toast(e.message, "err"); } finally { setBusy(false); }
  }
  return (
    <>
      {node}
      <PageHeader title="Automation Settings" subtitle="You stay in control. Review-before-submit is the default." />
      <ErrorBox message={error} />
      <div className="mb-4 flex items-center justify-between rounded-xl border border-slate-200 bg-white p-4">
        <div><div className="font-medium">{f.paused ? "Automation is paused" : "Automation is active"}</div><div className="text-sm text-slate-500">Pausing stops scheduled searches, resume generation and any automatic submission immediately.</div></div>
        <Button variant={f.paused ? "primary" : "danger"} busy={busy} onClick={() => save({ paused: !f.paused })}>{f.paused ? "Resume" : "Pause now"}</Button>
      </div>
      {f.sandbox_mode && <div className="mb-4"><Notice tone="warn">Sandbox mode is ON: the only submitter is a test double that never contacts employers. Applications are not really sent.</Notice></div>}
      <Card title="Automation level">
        <div className="space-y-3">
          {MODES.map(([v, label, desc]) => (
            <label key={v} className={`flex cursor-pointer gap-3 rounded-lg border p-3 ${f.mode === v ? "border-brand-500 bg-brand-50" : "border-slate-200"}`}>
              <input type="radio" name="mode" checked={f.mode === v} onChange={() => setF({ ...f, mode: v })} className="mt-1" />
              <span><span className="block font-medium">{label}</span><span className="text-sm text-slate-500">{desc}</span></span>
            </label>
          ))}
          {f.mode === "auto_submit_authorized" && !f.auto_submit_consent_at && (
            <label className="flex gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm">
              <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
              I authorize JobPilot to submit applications automatically through authorized integrations using my approved, validated resume. I understand it will not answer legal attestations, demographic, salary or eligibility questions for me, and that I can pause at any time.
            </label>
          )}
          <Button busy={busy} disabled={f.mode === "auto_submit_authorized" && !f.auto_submit_consent_at && !consent} onClick={() => save({ mode: f.mode, ...(consent ? { consent_to_auto_submit: true } : {}) })}>Save automation level</Button>
        </div>
      </Card>
      <Card title="AI assistance (optional)" className="mt-4">
        <div className="space-y-3 text-sm">
          <p>With AI on, Claude (a) judges how well each job fits your resume by meaning, not just keywords, and (b) rewrites your resume bullets for each job. Every rewrite is machine-checked against your original resume and audited by a second AI pass, and is discarded in favour of the safe rules-based version if it adds anything you have not documented. You still approve every resume.</p>
          <Notice tone="warn">{f.ai_disclosure}</Notice>
          {!f.ai_available ? <Notice>No AI provider is configured on this server. Ask the administrator to set <code>LLM_PROVIDER=anthropic</code> and <code>ANTHROPIC_API_KEY</code>.</Notice> : (
            <label className="flex items-start gap-2">
              <input type="checkbox" className="mt-1" checked={!!f.ai_enabled} onChange={(e) => save({ ai_enabled: e.target.checked })} />
              <span>Use AI ({f.ai_model}) for job matching, resume rewriting and keyword suggestions. I understand what is sent.</span>
            </label>)}
          {f.ai_enabled && f.ai_consent_at && <p className="text-xs text-slate-500">Enabled {new Date(f.ai_consent_at).toLocaleString()}.</p>}
        </div>
      </Card>
      <Card title="Schedule, documents & notifications" className="mt-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Search every (hours)" hint="Default 24. Runs on the server even when you're logged out."><Input type="number" min={1} max={168} value={f.run_interval_hours} onChange={(e) => setF({ ...f, run_interval_hours: +e.target.value })} /></Field>
          <Field label="Prepare applications for jobs scoring at least" hint="0–100"><Input type="number" min={0} max={100} value={f.auto_prepare_min_score} onChange={(e) => setF({ ...f, auto_prepare_min_score: +e.target.value })} /></Field>
          <Field label="Report delivery hour (your time zone)"><Input type="number" min={0} max={23} value={f.report_hour_local} onChange={(e) => setF({ ...f, report_hour_local: +e.target.value })} /></Field>
          <Field label="Data retention (days)"><Input type="number" min={30} max={3650} value={f.data_retention_days} onChange={(e) => setF({ ...f, data_retention_days: +e.target.value })} /></Field>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.cover_letters_enabled} onChange={(e) => setF({ ...f, cover_letters_enabled: e.target.checked })} /> Generate a cover letter for each prepared application</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.email_notifications} onChange={(e) => setF({ ...f, email_notifications: e.target.checked })} /> Email me the daily report</label>
        </div>
        <div className="mt-4"><Button busy={busy} onClick={() => save({ run_interval_hours: f.run_interval_hours, auto_prepare_min_score: f.auto_prepare_min_score, report_hour_local: f.report_hour_local, data_retention_days: f.data_retention_days, cover_letters_enabled: f.cover_letters_enabled, email_notifications: f.email_notifications })}>Save</Button></div>
      </Card>
    </>
  );
}
