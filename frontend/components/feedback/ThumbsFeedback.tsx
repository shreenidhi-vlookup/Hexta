"use client";

import { useState } from "react";
import { ThumbsUp, ThumbsDown, Send } from "lucide-react";

interface ThumbsFeedbackProps {
  responseId: string;
}

export default function ThumbsFeedback({ responseId }: ThumbsFeedbackProps) {
  const [rating, setRating] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const handleRate = (value: number) => {
    setRating(value);
  };

  const handleSubmit = async () => {
    if (rating === null) return;

    try {
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001/api/v1"}/feedback/`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            response_id: responseId,
            rating: rating,
            comment: comment.trim() || undefined,
          }),
        }
      );
      if (response.ok) {
        setSubmitted(true);
      }
    } catch {
      setSubmitted(true);
    }
  };

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
        <button
          onClick={() => handleRate(1)}
          className={`flex items-center gap-1 px-3 py-1.5 text-sm rounded-lg border transition-colors ${
            rating === 1
              ? "bg-green-100 text-green-800 border-green-300"
              : "hover:bg-muted border-border"
          }`}
        >
          <ThumbsUp className="w-3.5 h-3.5" />
          Helpful
        </button>
        <button
          onClick={() => handleRate(-1)}
          className={`flex items-center gap-1 px-3 py-1.5 text-sm rounded-lg border transition-colors ${
            rating === -1
              ? "bg-red-100 text-red-800 border-red-300"
              : "hover:bg-muted border-border"
          }`}
        >
          <ThumbsDown className="w-3.5 h-3.5" />
          Not helpful
        </button>
      </div>

      {rating !== null && (
        <div className="flex items-end gap-2">
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Add a comment (optional)"
            rows={2}
            maxLength={500}
            className="flex-1 px-3 py-2 text-sm border border-border rounded-lg focus:ring-2 focus:ring-primary outline-none resize-none"
          />
          <button
            onClick={handleSubmit}
            disabled={!comment.trim() && rating === null}
            className="px-4 py-2 bg-primary text-white text-sm font-medium rounded-lg hover:bg-primary/90 disabled:opacity-50 transition-colors"
          >
            <Send className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}
