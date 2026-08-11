"use client";

import { useState } from "react";
import { UserPlus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertCircle } from "lucide-react";
import { createUser } from "@/lib/api-client";
import { getToken } from "@/lib/auth";

const ROLES = ["loan_officer", "admin", "underwriter", "compliance"];
const DEPARTMENTS = ["general", "compliance", "underwriting"];

function parseList(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

export default function CreateUserForm({ onSuccess }: { onSuccess?: () => void }) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState("loan_officer");
  const [department, setDepartment] = useState("general");
  const [allowedDepts, setAllowedDepts] = useState("");
  const [clientId, setClientId] = useState("");
  const [assignedClients, setAssignedClients] = useState("");
  const [assignedCases, setAssignedCases] = useState("");
  const [creating, setCreating] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  const reset = () => {
    setEmail("");
    setPassword("");
    setFullName("");
    setRole("loan_officer");
    setDepartment("general");
    setAllowedDepts("");
    setClientId("");
    setAssignedClients("");
    setAssignedCases("");
    setResult(null);
  };

  const onSubmit = async () => {
    setCreating(true);
    setResult(null);
    try {
      const token = getToken() ?? "";
      const res = await createUser(
        {
          email,
          password,
          full_name: fullName || null,
          role,
          department,
          allowed_departments: parseList(allowedDepts),
          client_id: clientId || null,
          assigned_clients: parseList(assignedClients),
          assigned_cases: parseList(assignedCases),
        },
        token
      );
      setResult({ ok: true, message: `User ${res.user.email} created.` });
      onSuccess?.();
    } catch (err) {
      setResult({
        ok: false,
        message: err instanceof Error ? err.message : "Failed to create user.",
      });
    } finally {
      setCreating(false);
    }
  };

  if (!open) {
    return (
      <Button type="button" variant="outline" size="sm" onClick={() => setOpen(true)}>
        <UserPlus className="h-4 w-4 mr-2" /> Create user
      </Button>
    );
  }

  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold">Create user</h3>
        <button
          type="button"
          onClick={() => {
            setOpen(false);
            reset();
          }}
          aria-label="Close create user form"
          className="text-muted-foreground hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="cu-email" className="text-xs uppercase tracking-wide text-muted-foreground">
            Email
          </Label>
          <Input
            id="cu-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="user@company.com"
            required
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="cu-password" className="text-xs uppercase tracking-wide text-muted-foreground">
            Password (min 8 chars)
          </Label>
          <Input
            id="cu-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Temporary password"
            required
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="cu-name" className="text-xs uppercase tracking-wide text-muted-foreground">
            Full name
          </Label>
          <Input
            id="cu-name"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            placeholder="Jane Doe"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="cu-role" className="text-xs uppercase tracking-wide text-muted-foreground">
            Role
          </Label>
          <select
            id="cu-role"
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            value={role}
            onChange={(e) => setRole(e.target.value)}
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="cu-dept" className="text-xs uppercase tracking-wide text-muted-foreground">
            Department
          </Label>
          <select
            id="cu-dept"
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            value={department}
            onChange={(e) => setDepartment(e.target.value)}
          >
            {DEPARTMENTS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="cu-allowed" className="text-xs uppercase tracking-wide text-muted-foreground">
            Allowed departments (comma-separated)
          </Label>
          <Input
            id="cu-allowed"
            value={allowedDepts}
            onChange={(e) => setAllowedDepts(e.target.value)}
            placeholder="general, compliance"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="cu-client" className="text-xs uppercase tracking-wide text-muted-foreground">
            Client ID
          </Label>
          <Input
            id="cu-client"
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            placeholder="client-001 (optional)"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="cu-clients" className="text-xs uppercase tracking-wide text-muted-foreground">
            Assigned clients (comma-separated)
          </Label>
          <Input
            id="cu-clients"
            value={assignedClients}
            onChange={(e) => setAssignedClients(e.target.value)}
            placeholder="client-001, client-002"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="cu-cases" className="text-xs uppercase tracking-wide text-muted-foreground">
            Assigned cases (comma-separated)
          </Label>
          <Input
            id="cu-cases"
            value={assignedCases}
            onChange={(e) => setAssignedCases(e.target.value)}
            placeholder="case-100, case-101"
          />
        </div>
      </div>

      {result && (
        <Alert variant={result.ok ? "default" : "destructive"} className="mt-3">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>{result.ok ? "Created" : "Creation failed"}</AlertTitle>
          <AlertDescription>{result.message}</AlertDescription>
        </Alert>
      )}

      <div className="mt-4 flex items-center gap-2">
        <Button
          type="button"
          size="sm"
          disabled={creating || !email || !password}
          onClick={onSubmit}
        >
          {creating ? "Creating…" : "Create user"}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => {
            setOpen(false);
            reset();
          }}
        >
          Cancel
        </Button>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        Assigning an elevated role (admin/underwriter/compliance) requires super_admin.
      </p>
    </div>
  );
}
