"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

interface RelatedQuestionsProps {
  questions: string[];
  onAskQuestion?: (question: string) => void;
}

export default function RelatedQuestions({
  questions,
  onAskQuestion,
}: RelatedQuestionsProps) {
  if (!questions || questions.length === 0) return null;

  const [expanded, setExpanded] = useState(true);

  return (
    <div className="mt-6 border-t border-border pt-4">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
      >
        {expanded ? (
          <ChevronUp className="w-4 h-4" />
        ) : (
          <ChevronDown className="w-4 h-4" />
        )}
        Related Questions ({questions.length})
      </button>

      {expanded && (
        <div className="mt-3 space-y-2">
          {questions.map((q, i) => (
            <button
              key={i}
              onClick={() => onAskQuestion?.(q)}
              className="block w-full text-left p-2.5 text-sm rounded-lg border border-border hover:bg-muted/50 transition-colors text-wrap"
            >
              {q}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
