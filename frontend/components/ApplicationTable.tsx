"use client";
import Link from "next/link";
import { useState } from "react";
import { download, fmtDay, useApi } from "@/lib/api";
import { Button, Card, Empty, ErrorBox, Input, Loading, Pagination, ScoreBadge, Select, StatusBadge, Table, Td, Th } from "@/components/ui";

const ALL_STATUSES = ["awaiting_user_approval", "resume_ready_for_review", "ready_to_apply", "manual_application_required", "application_in_progress", "submitted",
  "submission_confirmation_pending", "application_failed", "interview", "offer_received", "rejected", "withdrawn", "closed_or_expired"];

export default function ApplicationTable({ fixedStatuses, full, empty }: { fixedStatuses?: string[]; full?: boolean; empty: { title: string; hint: string } }) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const st = status || fixedStatuses?.join(",") || "";
  const params = new URLSearchParams({ page: String(page), page_size: "25" });
  if (q) params.set("q", q);
  if (st) params.set("status", st);
  const { data, error, loading } = useApi<any>(`/api/applications?${params}`);
  const salary = (s: any) => (s ? `${s.min ?? "?"}–${s.max ?? "?"} ${s.currency || ""}` : "—");
  return (
    <Card>
      <div className="mb-4 flex flex-wrap gap-3">
        <Input aria-label="Search applications" placeholder="Search company, title or notes" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} className="max-w-xs" />
        <Select aria-label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} className="w-auto">
          <option value="">{fixedStatuses ? "All in this view" : "All statuses"}</option>
          {(fixedStatuses || ALL_STATUSES).map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}
        </Select>
        {full && <Button variant="secondary" className="ml-auto" onClick={() => download(`/api/applications/export.csv?${new URLSearchParams({ ...(q ? { q } : {}), ...(st ? { status: st } : {}) })}`, "applications.csv")}>Export CSV</Button>}
      </div>
      <ErrorBox message={error} />
      {loading && !data ? <Loading /> : data && data.items.length === 0 ? <Empty {...empty} /> : data && (
        <>
          <Table>
            <thead><tr><Th>Company</Th><Th>Job title</Th><Th>Status</Th><Th>Match</Th>
              {full && <><Th>Location</Th><Th>Type</Th><Th>Salary</Th><Th>Posted</Th><Th>Discovered</Th></>}
              <Th>Prepared</Th><Th>Applied</Th>
              {full && <><Th>Source</Th><Th>Resume</Th><Th>Cover letter</Th><Th>Method</Th><Th>Reference</Th><Th>Follow-up</Th><Th>Notes</Th></>}
            </tr></thead>
            <tbody className="divide-y divide-slate-100">
              {data.items.map((a: any) => (
                <tr key={a.id} className="hover:bg-slate-50">
                  <Td className="font-medium">{a.company}</Td>
                  <Td><Link href={`/history/${a.id}`} className="font-medium text-brand-700 hover:underline">{a.job_title}</Link></Td>
                  <Td><StatusBadge status={a.status} /></Td>
                  <Td><ScoreBadge score={a.job_match} /></Td>
                  {full && <><Td>{a.location || "—"}</Td><Td>{a.employment_type?.replace(/_/g, " ") || "—"}</Td><Td>{salary(a.salary)}</Td><Td>{fmtDay(a.date_posted)}</Td><Td>{fmtDay(a.date_discovered)}</Td></>}
                  <Td>{fmtDay(a.date_prepared)}</Td>
                  <Td>{a.date_applied ? fmtDay(a.date_applied) : <span className="text-slate-400">not applied</span>}</Td>
                  {full && <><Td>{a.source || "—"}{a.job_url && <> · <a className="text-brand-700 hover:underline" href={a.job_url} target="_blank" rel="noopener noreferrer">link</a></>}</Td>
                    <Td>{a.resume_version || "—"}</Td><Td>{a.cover_letter_version || "—"}</Td><Td>{a.submission_method || "—"}</Td>
                    <Td>{a.external_reference || "—"}</Td><Td>{a.follow_up_date ? fmtDay(a.follow_up_date) : "—"}</Td><Td className="max-w-xs truncate">{a.notes || ""}</Td></>}
                </tr>
              ))}
            </tbody>
          </Table>
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={setPage} />
        </>
      )}
    </Card>
  );
}
