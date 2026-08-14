"use client";

import { useEffect, useState, useRef } from "react";
import { Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertCircle } from "lucide-react";
import {
  fetchDocumentCategories,
  uploadDocument,
  type DocumentCategories,
} from "@/lib/api-client";
import { getToken } from "@/lib/auth";

export default function UploadForm({ onSuccess }: { onSuccess?: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(
    null,
  );
  // Rendered from the backend vocabulary rather than a local copy, so a
  // new category needs no frontend change. Null means the lookup failed;
  // the form still uploads, and the backend applies its own defaults.
  const [categories, setCategories] = useState<DocumentCategories | null>(null);
  const [docType, setDocType] = useState("");
  const [department, setDepartment] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const token = getToken() ?? "";
    fetchDocumentCategories(token)
      .then((c) => {
        setCategories(c);
        setDocType(c.auto_doc_type);
        setDepartment(c.default_department);
      })
      .catch(() => setCategories(null));
  }, []);

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setResult(null);
    const f = e.target.files?.[0] ?? null;
    setFile(f);
  };

  const onUpload = async () => {
    if (!file) {
      setResult({ ok: false, message: "Choose a file first." });
      return;
    }
    setUploading(true);
    setResult(null);
    try {
      const token = getToken() ?? "";
      const res = await uploadDocument(
        file,
        token,
        categories ? { docType, department } : undefined,
      );
      setResult({
        ok: true,
        message: res.indexing
          ? res.message
          : `${res.message} The document will not be indexed automatically.`,
      });
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
      onSuccess?.();
    } catch (err) {
      setResult({
        ok: false,
        message: err instanceof Error ? err.message : "Upload failed.",
      });
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-3">
      {categories && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <Label
              htmlFor="doc-type"
              className="text-xs uppercase tracking-wide text-muted-foreground"
            >
              Document type
            </Label>
            <Select
              value={docType}
              onValueChange={setDocType}
              disabled={uploading}
            >
              <SelectTrigger id="doc-type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {/* Detection stays available and is labelled, so its
                    behaviour is visible rather than implied. */}
                <SelectItem value={categories.auto_doc_type}>
                  Auto-detect from content
                </SelectItem>
                {categories.doc_types.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label
              htmlFor="doc-department"
              className="text-xs uppercase tracking-wide text-muted-foreground"
            >
              Department
            </Label>
            <Select
              value={department}
              onValueChange={setDepartment}
              disabled={uploading}
            >
              <SelectTrigger id="doc-department">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {categories.departments.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      )}

      <div className="flex items-end gap-3">
        <div className="flex-1">
          <Label htmlFor="doc-file" className="text-xs uppercase tracking-wide text-muted-foreground">
            Document file
          </Label>
          <Input
            id="doc-file"
            type="file"
            accept=".pdf,.docx,.doc,.txt,.pptx,.ppt,.xlsx,.csv,.md,.html,.htm,.rtf"
            onChange={onFileChange}
            ref={inputRef}
            disabled={uploading}
          />
        </div>
        <Button
          type="button"
          size="sm"
          disabled={uploading || !file}
          onClick={onUpload}
        >
          {uploading ? "Uploading…" : (
            <>
              <Upload className="h-4 w-4 mr-2" /> Upload
            </>
          )}
        </Button>
      </div>

      {file && (
        <div className="flex items-center justify-between rounded-md border bg-muted/40 px-3 py-1.5 text-sm">
          <span className="truncate">{file.name}</span>
          <span className="text-xs text-muted-foreground">
            {(file.size / 1024).toFixed(1)} KB
          </span>
        </div>
      )}

      {result && (
        <Alert variant={result.ok ? "default" : "destructive"}>
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>{result.ok ? "Uploaded" : "Upload failed"}</AlertTitle>
          <AlertDescription>{result.message}</AlertDescription>
        </Alert>
      )}
      {/* Both lines below were rewritten when access moved from department
          to client ownership. The old copy told the user department
          controlled who could retrieve a document, which is no longer true
          and is the kind of wrong that gets a document filed in the wrong
          place on purpose. */}
      <p className="text-xs text-muted-foreground">
        Type and department organise the knowledge base — every member of
        staff can retrieve this document once it is approved.
      </p>
      <p className="text-xs text-muted-foreground">
        An administrator reviews each upload before it becomes searchable.
        Supported formats: PDF, DOCX, DOC, TXT, PPT/PPTX, XLS/XLSX, CSV, MD,
        HTML, RTF.
      </p>
    </div>
  );
}
