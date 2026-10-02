"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { Button, Card, ErrorBox, Field, Input, Notice, Select, Textarea } from "@/components/ui";

const SITES = ["LinkedIn", "Indeed", "jobs.ch", "jobup.ch", "Other"];
const EMPLOYMENT = [["", "Not stated"], ["permanent", "Permanent / full-time"], ["part_time", "Part-time"], ["fixed_term", "Fixed-term contract"], ["temporary", "Temporary"], ["freelance", "Freelance"], ["contract_to_hire", "Contract-to-hire"], ["internship", "Internship"]];

export default function ImportJob({ onDone, onCancel }: { onDone: (jobId: number) => void; onCancel: () => void }) {
  const [f, setF] = useState({ site: "LinkedIn", url: "", title: "", company: "", location: "", description: "", employment_type: "", remote_status: "" });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: string) => setF({ ...f, [k]: v });
  async function submit() {
    setBusy(true); setErr(null);
    try {
      const body: any = { ...f };
      for (const k of ["url", "location", "employment_type", "remote_status"]) if (!body[k]) delete body[k];
      const r = await api("/api/jobs/import", { body });
      onDone(r.job_id);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  return (
    <Card title="Add a job manually" actions={<Button variant="ghost" onClick={onCancel}>Close</Button>} className="mb-4">
      <div className="space-y-3">
        <Notice>For jobs you found on LinkedIn, Indeed, jobs.ch or anywhere else. JobPilot does <b>not</b> open or fetch the link: it only stores the text you paste, so no site&apos;s access rules are involved. The job is matched against your first active search profile and shown even if it scores below your minimum.</Notice>
        <ErrorBox message={err} />
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Found on"><Select value={f.site} onChange={(e) => set("site", e.target.value)}>{SITES.map((s) => <option key={s}>{s}</option>)}</Select></Field>
          <Field label="Link to the posting (optional)" hint="Used for the Apply link and to avoid duplicates."><Input value={f.url} onChange={(e) => set("url", e.target.value)} placeholder="https://…" className="sm:col-span-2" /></Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Job title"><Input value={f.title} onChange={(e) => set("title", e.target.value)} /></Field>
          <Field label="Company"><Input value={f.company} onChange={(e) => set("company", e.target.value)} /></Field>
          <Field label="Location"><Input value={f.location} onChange={(e) => set("location", e.target.value)} placeholder="Zürich" /></Field>
          <Field label="Employment type"><Select value={f.employment_type} onChange={(e) => set("employment_type", e.target.value)}>{EMPLOYMENT.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select></Field>
          <Field label="Work mode"><Select value={f.remote_status} onChange={(e) => set("remote_status", e.target.value)}><option value="">Not stated</option><option value="remote">Remote</option><option value="hybrid">Hybrid</option><option value="onsite">On-site</option></Select></Field>
        </div>
        <Field label="Job description" hint="Copy the full text of the posting and paste it here (at least a few sentences)."><Textarea rows={10} value={f.description} onChange={(e) => set("description", e.target.value)} /></Field>
        <Button busy={busy} onClick={submit}>Add job</Button>
      </div>
    </Card>
  );
}
