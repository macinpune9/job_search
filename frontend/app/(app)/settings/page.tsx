"use client";
import { useEffect, useState } from "react";
import { api, token, useApi } from "@/lib/api";
import { Button, Card, Field, Input, Loading, Notice, PageHeader, Select, useToast } from "@/components/ui";

export default function Settings() {
  const { data: me, loading, reload } = useApi<any>("/api/users/me");
  const [tz, setTz] = useState("UTC");
  const [confirm, setConfirm] = useState("");
  const { toast, node } = useToast();
  useEffect(() => { if (me) setTz(me.timezone); }, [me]);
  if (loading || !me) return <Loading />;
  const zones: string[] = (Intl as any).supportedValuesOf ? (Intl as any).supportedValuesOf("timeZone") : ["UTC"];
  async function exportData() {
    const d = await api("/api/users/me/export");
    const url = URL.createObjectURL(new Blob([JSON.stringify(d, null, 2)], { type: "application/json" }));
    const a = document.createElement("a"); a.href = url; a.download = "jobpilot-export.json"; a.click(); URL.revokeObjectURL(url);
  }
  return (
    <>
      {node}
      <PageHeader title="Settings and Privacy" />
      <div className="grid max-w-3xl gap-4">
        <Card title="Account">
          <div className="space-y-3">
            <div className="text-sm">Email: <b>{me.email}</b> {me.email_verified ? "(verified)" : "(not verified)"}</div>
            <Field label="Time zone" hint="All times are stored in UTC and shown in this zone."><Select value={tz} onChange={(e) => setTz(e.target.value)}>{[...new Set([me.timezone, "UTC", ...zones])].map((z) => <option key={z}>{z}</option>)}</Select></Field>
            <Button onClick={async () => { try { await api("/api/users/me", { method: "PATCH", body: { timezone: tz } }); toast("Saved"); reload(); } catch (e: any) { toast(e.message, "err"); } }}>Save</Button>
          </div>
        </Card>
        <Card title="Your data">
          <div className="space-y-3 text-sm text-slate-600">
            <p>Resumes, contact details, salary preferences and application history are sensitive. Files are encrypted at rest and only you can access them. With the default “rules” AI provider, no resume content is sent to any third party.</p>
            <Button variant="secondary" onClick={exportData}>Download all my data (JSON)</Button>
          </div>
        </Card>
        <Card title="Delete account">
          <div className="space-y-3">
            <Notice tone="warn">This permanently deletes your account, resumes, generated documents, jobs matches, applications and history. It cannot be undone.</Notice>
            <Field label="Type DELETE to confirm"><Input value={confirm} onChange={(e) => setConfirm(e.target.value)} /></Field>
            <Button variant="danger" disabled={confirm !== "DELETE"} onClick={async () => { await api("/api/users/me", { method: "DELETE" }); token.clear(); window.location.href = "/register"; }}>Delete my account</Button>
          </div>
        </Card>
      </div>
    </>
  );
}
