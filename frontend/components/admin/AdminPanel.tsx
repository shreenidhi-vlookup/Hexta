"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Card,
  CardHeader,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  getAdminAudit,
  getAdminDocuments,
  getAdminFeedback,
  getAdminStats,
  getAdminUsers,
  getKnowledgeGaps,
  updateUserAdmin,
  approveDocument,
} from "@/lib/api-client";
import type {
  AdminDocument,
  AdminStats,
  AdminUser,
  AuditEntry,
  FeedbackEntry,
  KnowledgeGap,
} from "@/lib/api-client";
import { getToken, getTokenRole } from "@/lib/auth";
import { cn } from "@/lib/utils";
import type { AdminSection } from "@/components/nav/HomeSidebar";
import { RefreshCw, CheckCircle } from "lucide-react";
import UploadForm from "./UploadForm";
import { acknowledgeGap } from "@/lib/api-client";

interface AdminPanelState {
  stats: AdminStats | null;
  users: AdminUser[];
  documents: AdminDocument[];
  audit: AuditEntry[];
  feedback: FeedbackEntry[];
  gaps: KnowledgeGap[];
}

export function useAdminData() {
  const [data, setData] = useState<AdminPanelState>({
    stats: null,
    users: [],
    documents: [],
    audit: [],
    feedback: [],
    gaps: [],
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const token = getToken();
    if (!token) return;

    const results = await Promise.allSettled([
      getAdminStats(token),
      getAdminUsers(token),
      getAdminDocuments(token),
      getAdminAudit(token),
      getAdminFeedback(token),
      getKnowledgeGaps(token),
    ]);

    const [s, u, d, a, f, g] = results;
    setData((prev) => ({
      stats: s.status === "fulfilled" ? s.value.stats : prev.stats,
      users: u.status === "fulfilled" ? u.value.users : prev.users,
      documents: d.status === "fulfilled" ? d.value.documents : prev.documents,
      audit: a.status === "fulfilled" ? a.value.audit : prev.audit,
      feedback: f.status === "fulfilled" ? f.value.feedback : prev.feedback,
      gaps: g.status === "fulfilled" ? g.value.knowledge_gaps : prev.gaps,
    }));

    if (results.some((r) => r.status === "rejected")) {
      setError("Some sections failed to load. Try refreshing.");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return { ...data, loading, error, refresh: load };
}

function DataTable<T>({
  columns,
  rows,
  empty = "No records",
}: {
  columns: {
    key: string;
    header: string;
    render?: (row: T) => React.ReactNode;
    className?: string;
  }[];
  rows: T[];
  empty?: string;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border bg-card">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
            {columns.map((c) => (
              <th
                key={c.key}
                className="px-4 py-2.5 font-medium whitespace-nowrap"
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                className="px-4 py-10 text-center text-muted-foreground"
              >
                {empty}
              </td>
            </tr>
          ) : (
            rows.map((row, i) => (
              <tr key={i} className="border-b last:border-0 hover:bg-muted/40">
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={cn("px-4 py-2 align-top", c.className)}
                  >
                    {c.render
                      ? c.render(row)
                      : String((row as Record<string, unknown>)[c.key] ?? "")}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function StatCard({
  label,
  value,
  hint,
}: { label: string; value: number | string; hint?: string }) {
  return (
    <Card className="border-muted">
      <CardHeader className="p-4">
        <CardDescription className="text-xs font-medium uppercase tracking-wide">
          {label}
        </CardDescription>
        <div className="text-2xl font-bold leading-none">{value}</div>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </CardHeader>
    </Card>
  );
}

const OUTCOME_VARIANTS: Record<
  string,
  "default" | "secondary" | "destructive" | "outline"
> = {
  answer: "default",
  partial: "secondary",
  no_answer: "destructive",
};

function OutcomeBadge({ outcome }: { outcome: string | null }) {
  const value = outcome ?? "unknown";
  return (
    <Badge variant={OUTCOME_VARIANTS[value] ?? "outline"}>{value}</Badge>
  );
}

function StatusBadge({ active }: { active: boolean }) {
  return active ? (
    <Badge variant="secondary">Active</Badge>
  ) : (
    <Badge variant="outline">Inactive</Badge>
  );
}

function truncate(s: string | null | undefined, n = 80): string {
  if (!s) return "—";
  return s.length > n ? `${s.slice(0, n)}…` : s;
}

function fmtDate(iso?: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

function confidenceCell(value: number | null) {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(1)}%`;
}

const SECTION_TITLE: Record<AdminSection, string> = {
  dashboard: "Dashboard",
  users: "Users",
  documents: "Documents",
  audit: "Audit log",
  feedback: "Feedback",
  gaps: "Knowledge gaps",
};

const SECTION_DESC: Record<AdminSection, string> = {
  dashboard: "Overview of the knowledge base, users, and system activity.",
  users: "Manage user accounts and roles.",
  documents: "Browse uploaded documents in the knowledge base.",
  audit: "Every user query with outcome and confidence.",
  feedback: "User feedback on answer quality.",
  gaps: "Queries that could not be answered confidently.",
};

export { DataTable, StatCard, OutcomeBadge, StatusBadge, truncate, fmtDate, confidenceCell };

const ROLES = ["super_admin", "admin", "loan_officer", "underwriter", "compliance"];

function UserActions({
  user,
  onSaved,
  savingId,
  setSavingId,
  setSaveError,
}: {
  user: AdminUser;
  onSaved: () => void;
  savingId: number | null;
  setSavingId: (id: number | null) => void;
  setSaveError: (e: string | null) => void;
}) {
  const [saving, setSaving] = useState(false);

  const update = async (patch: Partial<AdminUser> & { role?: string }) => {
    setSaving(true);
    setSavingId(user.id);
    setSaveError(null);
    try {
      const token = getToken() ?? "";
      await updateUserAdmin(user.id, patch, token);
      onSaved();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Update failed");
    } finally {
      setSaving(false);
      setSavingId(null);
    }
  };

  const disabled = saving && savingId === user.id;

  return (
    <div className="flex items-center gap-2">
      <select
        className="text-xs underline decoration-transparent outline-none underline-offset-2 focus:decoration-current"
        value={user.role}
        disabled={disabled}
        onChange={(e) => update({ role: e.target.value as AdminUser["role"] })}
        aria-label="Change role"
      >
        {ROLES.map((r) => (
          <option key={r} value={r}>
            {r}
          </option>
        ))}
      </select>
      <span className="text-xs text-muted-foreground">
        Clients: {user.assigned_clients?.length ? user.assigned_clients.join(", ") : "—"}
      </span>
      <span className="text-xs text-muted-foreground">
        Cases: {user.assigned_cases?.length ? user.assigned_cases.join(", ") : "—"}
      </span>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="h-6 px-2 text-xs"
        disabled={disabled}
        onClick={() => update({ is_active: !user.is_active })}
        aria-label={user.is_active ? "Deactivate" : "Activate"}
      >
        {user.is_active ? "Deactivate" : "Activate"}
      </Button>
      {disabled && <span className="text-xs text-muted-foreground">saving…</span>}
    </div>
  );
}

export function AdminSections({ active }: { active: AdminSection | "settings" | "help" }) {
  const { stats, users, documents, audit, feedback, gaps, loading, error, refresh } =
    useAdminData();
  const [savingId, setSavingId] = useState<number | null>(null);
  const [savingDocId, setSavingDocId] = useState<number | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const isSuperAdmin = getTokenRole(getToken() ?? "") === "super_admin";
  const answered = stats ? Math.max(stats.queries - stats.no_answer, 0) : 0;

  const isData = active !== "settings" && active !== "help";

  if (!isData) {
    return (
      <div className="p-6">
        <div className="mx-auto max-w-5xl">
          <h2 className="text-xl font-bold">
            {active === "settings" ? "Settings" : "Help"}
          </h2>
          <p className="mt-2 text-sm text-muted-foreground">
            {active === "settings"
              ? "Preferences for your session."
              : "Help and documentation."}
          </p>
        </div>
      </div>
    );
  }

  const section = active as AdminSection;

  if (loading && stats === null) {
    return (
      <div className="p-6">
        <div className="mx-auto max-w-5xl space-y-6">
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            {Array.from({ length: 7 }).map((_, i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
          <Skeleton className="h-64" />
        </div>
      </div>
    );
  }

  const renderBody = () => {
    switch (section) {
      case "dashboard":
        return (
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <StatCard label="Users" value={stats?.users ?? 0} hint={`${stats?.active_users ?? 0} active`} />
              <StatCard label="Documents" value={stats?.documents ?? 0} hint={`${stats?.active_documents ?? 0} active`} />
              <StatCard label="Chunks" value={stats?.chunks ?? 0} />
              <StatCard label="Total queries" value={stats?.queries ?? 0} hint={`${answered} answered · ${stats?.no_answer ?? 0} no answer`} />
              <StatCard label="Avg confidence" value={confidenceCell(stats?.avg_confidence ?? null)} />
              <StatCard label="Feedback" value={(stats?.thumbs_up ?? 0) + (stats?.thumbs_down ?? 0)} hint={`${stats?.thumbs_up ?? 0} up · ${stats?.thumbs_down ?? 0} down`} />
              <StatCard label="Knowledge gaps" value={stats?.knowledge_gaps ?? 0} hint="Low-confidence queries" />
            </div>
            <Card>
              <CardHeader className="pb-3 pt-4 px-4">
                <CardDescription className="text-sm font-semibold text-foreground">
                  Recent activity
                </CardDescription>
              </CardHeader>
              <div className="px-4 pb-4">
                <DataTable<AuditEntry>
                  columns={[
                    { key: "time", header: "Time", render: (r) => <span className="whitespace-nowrap text-muted-foreground">{fmtDate(r.created_at)}</span> },
                    { key: "email", header: "User", render: (r) => r.email ?? "—" },
                    { key: "query", header: "Query", render: (r) => truncate(r.query, 60) },
                    { key: "outcome", header: "Outcome", render: (r) => <OutcomeBadge outcome={r.outcome} /> },
                    { key: "confidence", header: "Confidence", render: (r) => confidenceCell(r.confidence) },
                  ]}
                  rows={stats?.recent_activity ?? []}
                  empty="No queries logged yet"
                />
              </div>
            </Card>
          </div>
        );

      case "users":
        return (
          <DataTable<AdminUser>
            columns={[
              { key: "id", header: "ID", render: (r) => <span className="text-muted-foreground">{r.id}</span> },
              { key: "name", header: "User", render: (r) => (
                <div>
                  <div className="font-medium">{r.full_name || "—"}</div>
                  <div className="text-xs text-muted-foreground">{r.email}</div>
                </div>
              ) },
               { key: "role", header: "Role", render: (r) => <Badge variant={r.role === "super_admin" || r.role === "admin" ? "default" : "secondary"}>{r.role}</Badge> },
               { key: "department", header: "Department", render: (r) => r.department },
               { key: "client", header: "Client ID", render: (r) => <span className="text-muted-foreground">{r.client_id || "—"}</span> },
               { key: "allowed", header: "Allowed departments", render: (r) => (r.allowed_departments?.length ? r.allowed_departments.join(", ") : "—") },
              { key: "status", header: "Status", render: (r) => <StatusBadge active={r.is_active} /> },
              { key: "actions", header: "Actions", render: (r) => isSuperAdmin ? <UserActions user={r} onSaved={refresh} savingId={savingId} setSavingId={setSavingId} setSaveError={setSaveError} /> : null },
              { key: "created", header: "Created", render: (r) => <span className="whitespace-nowrap text-muted-foreground">{fmtDate(r.created_at)}</span> },
            ]}
            rows={users}
            empty="No users found"
          />
        );

       case "documents":
         return (
           <div className="space-y-4">
             <UploadForm onSuccess={refresh} />
             <DataTable<AdminDocument>
             columns={[
               { key: "id", header: "ID", render: (r) => <span className="text-muted-foreground">{r.id}</span> },
               { key: "title", header: "Title", render: (r) => <span className="font-medium">{truncate(r.title, 70)}</span> },
               { key: "type", header: "Type", render: (r) => r.doc_type },
               { key: "department", header: "Department", render: (r) => r.department },
               { key: "version", header: "Version", render: (r) => <span className="text-muted-foreground">v{r.version}</span> },
               { key: "client", header: "Client ID", render: (r) => <span className="text-muted-foreground">{r.client_id || "—"}</span> },
               { key: "status", header: "Status", render: (r) => (
                 <div className="flex gap-1.5">
                   <StatusBadge active={r.is_active} />
                   {r.is_approved ? (
                     <Badge variant="default">Approved</Badge>
                   ) : (
                     <Badge variant="destructive">Pending</Badge>
                   )}
                 </div>
               ) },
               { key: "actions", header: "Actions", render: (r) => (
                 !r.is_approved && r.is_active ? (
                   <Button
                     type="button"
                     variant="outline"
                     size="sm"
                     className="h-6 text-xs"
                     disabled={savingDocId === r.id}
                     onClick={async () => {
                       const token = getToken() ?? "";
                       setSavingDocId(r.id);
                       try {
                         await approveDocument(r.id, token);
                         refresh();
                       } catch (err) {
                         setSaveError(err instanceof Error ? err.message : "Approval failed");
                       } finally {
                         setSavingDocId(null);
                       }
                     }}
                     aria-label={`Approve ${r.title}`}
                   >
                     {savingDocId === r.id ? "Approving…" : "Approve"}
                   </Button>
                 ) : null
               ) },
               { key: "created", header: "Created", render: (r) => <span className="whitespace-nowrap text-muted-foreground">{fmtDate(r.created_at)}</span> },
             ]}
             rows={documents}
             empty="No documents uploaded yet"
           />
           </div>
         );

      case "audit":
        return (
          <DataTable<AuditEntry>
            columns={[
              { key: "id", header: "ID", render: (r) => <span className="text-muted-foreground">{r.id}</span> },
              { key: "time", header: "Time", render: (r) => <span className="whitespace-nowrap text-muted-foreground">{fmtDate(r.created_at)}</span> },
              { key: "email", header: "User", render: (r) => r.email ?? "—" },
              { key: "query", header: "Query", render: (r) => truncate(r.query, 80) },
              { key: "outcome", header: "Outcome", render: (r) => <OutcomeBadge outcome={r.outcome} /> },
              { key: "confidence", header: "Confidence", render: (r) => confidenceCell(r.confidence) },
              { key: "latency", header: "Latency", render: (r) => (r.latency_ms != null ? `${Math.round(r.latency_ms)}ms` : "—") },
            ]}
            rows={audit}
            empty="No queries logged yet"
          />
        );

      case "feedback":
        return (
          <DataTable<FeedbackEntry>
            columns={[
              { key: "id", header: "ID", render: (r) => <span className="text-muted-foreground">{r.id}</span> },
              { key: "time", header: "Time", render: (r) => <span className="whitespace-nowrap text-muted-foreground">{fmtDate(r.created_at)}</span> },
              { key: "email", header: "User", render: (r) => r.email ?? "—" },
              { key: "rating", header: "Rating", render: (r) => (r.rating === 1 ? <Badge variant="default">Thumbs up</Badge> : <Badge variant="destructive">Thumbs down</Badge>) },
              { key: "comment", header: "Comment", render: (r) => truncate(r.comment, 100) },
              { key: "response_id", header: "Response", render: (r) => <span className="font-mono text-xs text-muted-foreground">{truncate(r.response_id, 24)}</span> },
            ]}
            rows={feedback}
            empty="No feedback submitted yet"
          />
        );

      case "gaps":
        return (
          <DataTable<KnowledgeGap>
            columns={[
              { key: "id", header: "ID", render: (r) => <span className="text-muted-foreground">{r.id}</span> },
              { key: "time", header: "Time", render: (r) => <span className="whitespace-nowrap text-muted-foreground">{fmtDate(r.created_at)}</span> },
              { key: "query", header: "Query", render: (r) => (
                <div className="font-medium">{truncate(r.query, 120)}</div>
              ) },
              { key: "intent", header: "Intent", render: (r) => r.intent || "—" },
              { key: "confidence", header: "Confidence", render: (r) => confidenceCell(r.confidence) },
              { key: "acknowledged", header: "Status", render: (r) => (
                r.acknowledged ? (
                  <Badge variant="secondary">
                    <CheckCircle className="h-3 w-3 mr-1" />
                    Acknowledged
                  </Badge>
                ) : (
                  <Badge variant="outline">Pending review</Badge>
                )
              ) },
              {
                key: "actions",
                header: "Actions",
                render: (r) => {
                  if (r.acknowledged) return null;
                  return (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-6 px-2 text-xs"
                      onClick={async () => {
                        const token = getToken() ?? "";
                        try {
                          await acknowledgeGap(r.id, token);
                          refresh();
                        } catch (err) {
                          // ignore
                        }
                      }}
                      aria-label={`Acknowledge gap ${r.id}`}
                    >
                      Mark reviewed
                    </Button>
                  );
                },
              },
            ]}
            rows={gaps}
            empty="No knowledge gaps recorded yet"
          />
        );
    }
  };

  return (
    <div className="p-6">
      <div className="mx-auto max-w-5xl space-y-6">
        <div className="flex items-center justify-between gap-2">
          <div>
            <h2 className="text-xl font-bold">{SECTION_TITLE[section]}</h2>
            <p className="text-sm text-muted-foreground">{SECTION_DESC[section]}</p>
          </div>
          <Button type="button" variant="outline" size="sm" onClick={refresh} disabled={loading}>
            <RefreshCw className={cn("h-4 w-4 mr-2", loading && "animate-spin")} />
            Refresh
          </Button>
        </div>

        {error && (
          <div className="rounded-lg border border-destructive/50 bg-destructive/10 px-4 py-2 text-sm text-destructive">
            {error}
          </div>
        )}

        {renderBody()}
      </div>
    </div>
  );
}
