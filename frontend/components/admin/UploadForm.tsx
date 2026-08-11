"use client";

import { useState, useRef } from "react";
import { Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertCircle } from "lucide-react";
import { uploadDocument } from "@/lib/api-client";
import { getToken } from "@/lib/auth";

export default function UploadForm({ onSuccess }: { onSuccess?: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(
    null,
  );
  const inputRef = useRef<HTMLInputElement>(null);

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
      const res = await uploadDocument(file, token);
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
      <p className="text-xs text-muted-foreground">
        Uploads are restricted to administrators. Supported formats: PDF, DOCX,
        DOC, TXT, PPT/PPTX, XLS/XLSX, CSV, MD, HTML, RTF.
      </p>
    </div>
  );
}
