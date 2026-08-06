"use client";

import { Settings2 } from "lucide-react";
import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { getUserSettings, updateUserSettings } from "@/lib/api-client";
import { getToken } from "@/lib/auth";
import { useCallback } from "react";

export default function SettingsDialog() {
  const [open, setOpen] = useState(false);
  const [showRelatedQuestions, setShowRelatedQuestions] = useState(true);
  const [saving, setSaving] = useState(false);

  const handleOpenChange = useCallback(async (isOpen: boolean) => {
    if (isOpen) {
      try {
        const token = getToken() ?? undefined;
        const settings = await getUserSettings(token);
        setShowRelatedQuestions(settings.show_related_questions);
      } catch {
        setShowRelatedQuestions(true);
      }
    }
    setOpen(isOpen);
  }, []);

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      const token = getToken() ?? undefined;
      await updateUserSettings(
        { show_related_questions: showRelatedQuestions },
        token,
      );
    } catch {
    } finally {
      setSaving(false);
      setOpen(false);
    }
  }, [showRelatedQuestions]);

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button type="button" variant="ghost" size="sm" aria-label="Settings">
          <Settings2 className="h-4 w-4" />
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Settings</DialogTitle>
          <DialogDescription>
            Control your chat experience preferences.
          </DialogDescription>
        </DialogHeader>
        <div className="flex items-center justify-between py-2">
          <Label htmlFor="show-related" className="text-sm">
            Show suggestion questions
          </Label>
          <Checkbox
            id="show-related"
            checked={showRelatedQuestions}
            onCheckedChange={(checked) =>
              setShowRelatedQuestions(checked === true)
            }
          />
        </div>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setOpen(false)}
          >
            Cancel
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}