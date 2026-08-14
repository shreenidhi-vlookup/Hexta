"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import UploadForm from "@/components/admin/UploadForm";
import { getMyDocuments, type AdminDocument } from "@/lib/api-client";
import { getToken } from "@/lib/auth";

/**
 * The Documents view a processor sees: contribute a document, and track
 * what happened to it.
 *
 * An uploaded document is deliberately unreachable until an admin approves
 * it, so without this list a processor has no way to tell "waiting for
 * review" from "the upload failed" — and would go and ask an admin, which
 * is the interruption this whole feature exists to remove. It shows only
 * their own uploads; the full document list stays admin-only.
 */
export default function MyDocuments() {
  const [documents, setDocuments] = useState<AdminDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getMyDocuments(getToken() ?? "");
      setDocuments(res.documents);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load your uploads.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  /**
   * Ingestion runs as a detached batch process, so the document row does
   * not exist yet when the upload request returns — refreshing only on
   * success shows an empty list and reads as "the upload failed". Re-fetch
   * a few seconds later so it appears without the user reloading.
   */
  const refreshAfterUpload = useCallback(() => {
    void refresh();
    const timer = setTimeout(() => void refresh(), 4000);
    return () => clearTimeout(timer);
  }, [refresh]);

  return (
    <div className="p-6">
      <div className="mx-auto max-w-5xl space-y-6">
        <div>
          <h2 className="text-xl font-bold">Documents</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Add a document to the knowledge base. An administrator reviews it
            before it becomes searchable.
          </p>
        </div>

        <UploadForm onSuccess={refreshAfterUpload} />

        <div>
          <h3 className="text-sm font-semibold">Your uploads</h3>
          {loading ? (
            <p className="mt-2 text-sm text-muted-foreground">Loading…</p>
          ) : error ? (
            <p className="mt-2 text-sm text-destructive">{error}</p>
          ) : documents.length === 0 ? (
            <p className="mt-2 text-sm text-muted-foreground">
              You haven&apos;t uploaded anything yet.
            </p>
          ) : (
            <ul className="mt-2 divide-y divide-border rounded-md border border-border">
              {documents.map((doc) => (
                <li
                  key={doc.id}
                  className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
                >
                  <div className="min-w-0">
                    <p className="truncate font-medium">{doc.title}</p>
                    <p className="text-xs text-muted-foreground">
                      {doc.doc_type} · {doc.department}
                    </p>
                  </div>
                  {doc.is_approved ? (
                    <Badge variant="default">Approved</Badge>
                  ) : (
                    <Badge variant="secondary">Pending review</Badge>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
