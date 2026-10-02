"use client";
import Link from "next/link";
import { useState } from "react";
import { fmtDay, useApi } from "@/lib/api";
import { Card, Empty, ErrorBox, Input, Loading, PageHeader, Pagination, ScoreBadge, Select, StatusBadge, Table, Td, Th } from "@/components/ui";

export default function Jobs() {
  const [q, setQ] = useState("");
  const [qualified, setQualified] = useState("true");
  const [minScore, setMinScore] = useState("");
  const [remote, setRemote] = useState("");
  const [source, setSource] = useState("");
  const [sort, setSort] = useState("score");
  const [page, setPage] = useState(1);
  const params = new URLSearchParams({ page: String(page), page_size: "25", sort });
  if (q) params.set("q", q);
  if (qualified !== "all") params.set("qualified", qualified);
  if (minScore) params.set("min_score", minScore);
  if (remote) params.set("remote", remote);
  if (source) params.set("source", source);
  const { data, error, loading } = useApi<any>(`/api/jobs?${params}`);
  const reset = (f: () => void) => { f(); setPage(1); };
  return (
    <>
      <PageHeader title="Discovered Jobs" subtitle="Every job found by your searches, with the reason it matched or was excluded." />
      <Card>
        <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
          <Input aria-label="Search" placeholder="Search title or company" value={q} onChange={(e) => reset(() => setQ(e.target.value))} className="lg:col-span-2" />
          <Select aria-label="Filter" value={qualified} onChange={(e) => reset(() => setQualified(e.target.value))}>
            <option value="true">Matching only</option><option value="false">Excluded only</option><option value="all">All discovered</option>
          </Select>
          <Input aria-label="Minimum score" type="number" min={0} max={100} placeholder="Min score" value={minScore} onChange={(e) => reset(() => setMinScore(e.target.value))} />
          <Select aria-label="Work mode" value={remote} onChange={(e) => reset(() => setRemote(e.target.value))}>
            <option value="">Any work mode</option><option value="remote">Remote</option><option value="hybrid">Hybrid</option><option value="onsite">On-site</option>
          </Select>
          <Select aria-label="Source" value={source} onChange={(e) => reset(() => setSource(e.target.value))}>
            <option value="">Any source</option><option value="greenhouse">Greenhouse</option><option value="lever">Lever</option><option value="ashby">Ashby</option>
          </Select>
        </div>
        <div className="mb-3 flex items-center gap-2 text-sm text-slate-500">Sort by
          <Select aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value)} className="w-auto"><option value="score">Match score</option><option value="posted">Date posted</option><option value="discovered">Date discovered</option></Select>
        </div>
        <ErrorBox message={error} />
        {loading && !data ? <Loading /> : data && data.items.length === 0 ? (
          <Empty title="No jobs to show" hint={qualified === "true" ? "Run a search from Job Search Preferences, or switch the filter to see excluded jobs and why." : "Nothing matches these filters."} />
        ) : data && (
          <>
            <Table>
              <thead><tr><Th>Match</Th><Th>Title</Th><Th>Company</Th><Th>Location</Th><Th>Posted</Th><Th>Discovered</Th><Th>Source</Th><Th>Status</Th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((j: any) => (
                  <tr key={j.id} className="hover:bg-slate-50">
                    <Td><ScoreBadge score={j.match_score} /></Td>
                    <Td><Link href={`/jobs/${j.id}`} className="font-medium text-brand-700 hover:underline">{j.title}</Link>
                      {j.needs_dedup_review && <span className="ml-2 rounded bg-amber-100 px-1.5 text-xs text-amber-800" title="Possible duplicate of another listing">review</span>}
                      {j.status === "closed" && <span className="ml-2 rounded bg-slate-200 px-1.5 text-xs">closed</span>}</Td>
                    <Td>{j.company}</Td>
                    <Td>{j.location || "—"}</Td>
                    <Td>{j.posted_at ? fmtDay(j.posted_at) : <span className="text-slate-400" title="Source gave no reliable publication date">unknown</span>}</Td>
                    <Td>{fmtDay(j.first_discovered_at)}</Td>
                    <Td>{j.sources.join(", ")}</Td>
                    <Td>{j.qualified ? <StatusBadge status={j.workflow_status} /> : <span className="text-xs text-slate-500">{j.exclusion_reasons?.[0]?.code?.replace(/_/g, " ")}</span>}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={setPage} />
          </>
        )}
      </Card>
    </>
  );
}
