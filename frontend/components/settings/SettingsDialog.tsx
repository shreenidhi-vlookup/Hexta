"use client";

import { Settings2 } from "lucide-react";
import { useCallback, useState } from "react";
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

interface SettingsDialogProps {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  onShowRelatedQuestionsChange?: (value: boolean) => void;
}

export default function SettingsDialog({
  open,
  onOpenChange,
  onShowRelatedQuestionsChange,
}: SettingsDialogProps) {
  const [internalOpen, setInternalOpen] = useState(false);
  const isOpen = open ?? internalOpen;
  const [showRelatedQuestions, setShowRelatedQuestions] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const handleOpenChange = useCallback(
    async (nextOpen: boolean) => {
      if (nextOpen) {
        setSaveError(null);
        try {
          const token = getToken() ?? undefined;
          const settings = await getUserSettings(token);
          setShowRelatedQuestions(settings.show_related_questions);
        } catch {
          setShowRelatedQuestions(true);
        }
      }
      onOpenChange?.(nextOpen);
      setInternalOpen(nextOpen);
    },
    [onOpenChange],
  );

  const handleSave = useCallback(async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const token = getToken() ?? undefined;
      await updateUserSettings(
        { show_related_questions: showRelatedQuestions },
        token,
      );
      onShowRelatedQuestionsChange?.(showRelatedQuestions);
      onOpenChange?.(false);
      setInternalOpen(false);
    } catch (err) {
      setSaveError(
        err instanceof Error ? err.message : "Could not save your settings",
      );
    } finally {
      setSaving(false);
    }
  }, [showRelatedQuestions, onShowRelatedQuestionsChange, onOpenChange]);

  const isControlled = open !== undefined;

  return (
    <Dialog open={isOpen} onOpenChange={handleOpenChange}>
      {!isControlled && (
        <DialogTrigger asChild>
          <Button type="button" variant="ghost" size="sm" aria-label="Settings">
            <Settings2 className="h-4 w-4" />
          </Button>
        </DialogTrigger>
      )}
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
        {saveError && (
          <p className="text-sm text-destructive">{saveError}</p>
        )}
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => { onOpenChange?.(false); setInternalOpen(false); }}
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