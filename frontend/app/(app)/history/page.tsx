"use client";
import ApplicationTable from "@/components/ApplicationTable";
import { PageHeader } from "@/components/ui";

export default function History() {
  return (
    <>
      <PageHeader title="Application History" subtitle="Every prepared and submitted application. Jobs are labelled by their real state — nothing is shown as applied unless it was confirmed." />
      <ApplicationTable full empty={{ title: "No applications yet", hint: "Prepare an application from a discovered job; it will appear here with its full event history." }} />
    </>
  );
}
