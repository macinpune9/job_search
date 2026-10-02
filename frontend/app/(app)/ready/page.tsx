"use client";
import ApplicationTable from "@/components/ApplicationTable";
import { Notice, PageHeader } from "@/components/ui";

export default function Ready() {
  return (
    <>
      <PageHeader title="Ready to Apply" subtitle="Tailored resumes waiting for your review, approved applications, and applications that need you to finish manually." />
      <div className="mb-4"><Notice>Open an item to compare your original resume with the tailored version, see what changed, approve it, and submit (or follow the manual package).</Notice></div>
      <ApplicationTable fixedStatuses={["awaiting_user_approval", "resume_ready_for_review", "ready_to_apply", "manual_application_required", "submission_confirmation_pending", "application_failed"]}
        empty={{ title: "Nothing waiting for you", hint: "New qualifying jobs with a validated resume will show up here after the next search." }} />
    </>
  );
}
