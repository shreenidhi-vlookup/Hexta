"use client";

import { useState } from "react";
import { ThumbsUp, ThumbsDown, Send, Loader2, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { submitFeedback } from "@/lib/api-client";
import { getToken } from "@/lib/auth";

interface ThumbsFeedbackProps {
  responseId: string;
  /** Icon-only thumbs placed inline next to the copy action */
  compact?: boolean;
}

export default function ThumbsFeedback({
  responseId,
  compact = false,
}: ThumbsFeedbackProps) {
  const [rating, setRating] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submitRating = async (value: 1 | -1, note?: string) => {
    setIsSubmitting(true);
    setError(null);
    try {
      await submitFeedback(
        {
          response_id: responseId,
          rating: value,
          comment: note?.trim() || undefined,
        },
        getToken() ?? undefined
      );
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Feedback submission failed");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRate = (value: number) => {
    setRating(value);
    setError(null);
  };

  const handleSubmit = async () => {
    if (rating === null) return;
    await submitRating(rating === 1 ? 1 : -1, comment);
  };

  if (compact) {
    if (submitted) {
      return (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 w-8 p-0 text-muted-foreground"
          aria-label="Feedback submitted"
        >
          <Check className="h-3.5 w-3.5 text-success" />
        </Button>
      );
    }
    return (
      <div className="flex items-center gap-0.5">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 w-8 p-0 text-muted-foreground hover:text-foreground"
          aria-pressed={rating === 1}
          aria-label="Rate as helpful"
          disabled={isSubmitting}
          onClick={() => submitRating(1)}
        >
          <ThumbsUp className="h-3.5 w-3.5" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 w-8 p-0 text-muted-foreground hover:text-foreground"
          aria-pressed={rating === -1}
          aria-label="Rate as not helpful"
          disabled={isSubmitting}
          onClick={() => submitRating(-1)}
        >
          <ThumbsDown className="h-3.5 w-3.5" />
        </Button>
      </div>
    );
  }

  if (submitted) {
    return (
      <div className="mt-4 text-sm text-muted-foreground">
        Thank you for your feedback!
      </div>
    );
  }

  return (
    <div className="mt-6 pt-4 border-t border-border">
      <p className="text-sm font-medium text-foreground mb-2">
        Was this helpful?
      </p>
      <div className="flex items-center gap-3 mb-3">
        <Button
          type="button"
          variant="outline"
          onClick={() => handleRate(1)}
          aria-pressed={rating === 1}
          className={cn(
            "flex items-center gap-1 text-sm rounded-lg",
            rating === 1 &&
              "bg-success/10 text-success border-success/40 hover:bg-success/10"
          )}
        >
          <ThumbsUp className="w-3.5 h-3.5" />
          Helpful
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => handleRate(-1)}
          aria-pressed={rating === -1}
          className={cn(
            "flex items-center gap-1 text-sm rounded-lg",
            rating === -1 &&
              "bg-destructive/10 text-destructive border-destructive/40 hover:bg-destructive/10"
          )}
        >
          <ThumbsDown className="w-3.5 h-3.5" />
          Not helpful
        </Button>
      </div>

      {error && <p className="mb-3 text-sm text-destructive">{error}</p>}

      {rating !== null && (
        <div className="space-y-2">
          <Label
            htmlFor={`feedback-comment-${responseId}`}
            className="text-sm text-muted-foreground"
          >
            Optional feedback
          </Label>
          <Textarea
            id={`feedback-comment-${responseId}`}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Tell us what could be improved..."
            rows={3}
            maxLength={500}
            className="resize-none"
          />
          <div className="flex justify-end">
            <Button
              type="button"
              onClick={handleSubmit}
              disabled={isSubmitting}
              aria-label="Submit feedback"
            >
              {isSubmitting ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Send className="w-3.5 h-3.5 mr-1.5" />
              )}
              Submit
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
