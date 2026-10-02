"use client";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { api, useApi } from "@/lib/api";
import { Button, Card, ErrorBox, Field, Input, Loading, Notice, PageHeader, Textarea, useToast } from "@/components/ui";

const schema = z.object({
  full_name: z.string().max(200).optional(), phone: z.string().max(64).optional(), location: z.string().max(200).optional(),
  linkedin_url: z.string().regex(/^(https:\/\/([a-z]{2,3}\.)?linkedin\.com\/in\/[A-Za-z0-9\-_%]{3,100}\/?)?$/, "Use a URL like https://www.linkedin.com/in/your-name").optional(),
  work_authorization: z.string().max(500).optional(),
});
type V = z.infer<typeof schema>;

export default function Profile() {
  const { data: p, loading, reload } = useApi<any>("/api/profiles/me");
  const { register, handleSubmit, reset, formState: { errors, isSubmitting } } = useForm<V>({ resolver: zodResolver(schema) });
  const [paste, setPaste] = useState("");
  const [imp, setImp] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const { toast, node } = useToast();
  useEffect(() => { if (p) reset({ full_name: p.full_name || "", phone: p.phone || "", location: p.location || "", linkedin_url: p.linkedin_url || "", work_authorization: p.work_authorization?.note || "" }); }, [p, reset]);
  if (loading) return <Loading />;

  const save = async (v: V) => {
    setErr(null);
    try {
      await api("/api/profiles/me", { method: "PATCH", body: { ...v, work_authorization: v.work_authorization ? { note: v.work_authorization } : null, linkedin_url: v.linkedin_url || null } });
      toast("Profile saved"); reload();
    } catch (e: any) { setErr(e.message); }
  };
  async function doImport() {
    setErr(null);
    try { setImp(await api("/api/profiles/linkedin/import", { body: { url: p?.linkedin_url || undefined, pasted_text: paste || undefined } })); reload(); } catch (e: any) { setErr(e.message); }
  }
  return (
    <>
      {node}
      <PageHeader title="My Profile" subtitle="Contact details and optional facts used when preparing applications. Nothing here is shared unless you choose to." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Contact & facts">
          <form onSubmit={handleSubmit(save)} className="space-y-3" noValidate>
            <ErrorBox message={err} />
            <Field label="Full name" error={errors.full_name?.message}><Input {...register("full_name")} /></Field>
            <Field label="Phone"><Input {...register("phone")} /></Field>
            <Field label="Location"><Input {...register("location")} /></Field>
            <Field label="LinkedIn profile URL" error={errors.linkedin_url?.message}><Input placeholder="https://www.linkedin.com/in/your-name" {...register("linkedin_url")} /></Field>
            <Field label="Work authorization / sponsorship (optional)" hint="Only used to pre-fill the manual application package if you supply it."><Textarea rows={2} {...register("work_authorization")} /></Field>
            <Button type="submit" busy={isSubmitting}>Save</Button>
          </form>
        </Card>
        <Card title="Import LinkedIn information">
          <div className="space-y-3">
            <Notice>LinkedIn does not allow automated scraping of profiles, and no authorized API is configured, so JobPilot never fetches your profile itself. Paste your profile text (or the text from LinkedIn&apos;s official data export) and review what was extracted.</Notice>
            <Textarea rows={8} placeholder="Paste your LinkedIn profile text here…" value={paste} onChange={(e) => setPaste(e.target.value)} />
            <Button variant="secondary" onClick={doImport}>Save URL / import pasted text</Button>
            {imp && !imp.imported && <Notice tone="warn">{imp.limitation}</Notice>}
            {imp?.imported && (
              <div className="space-y-2 text-sm">
                <div className="font-medium">Differences between LinkedIn and your resume</div>
                {imp.discrepancies.length === 0 ? <p className="text-emerald-700">No differences found.</p> :
                  <ul className="space-y-1">{imp.discrepancies.map((d: any, i: number) => <li key={i} className="text-slate-700"><b>{d.type.replace(/_/g, " ")}:</b> {d.detail}</li>)}</ul>}
                <p className="text-xs text-slate-500">Imported data is stored for comparison only. It never adds facts to a generated resume; your uploaded resume stays the source of truth.</p>
              </div>
            )}
          </div>
        </Card>
      </div>
    </>
  );
}
