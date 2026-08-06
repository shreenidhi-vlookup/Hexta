"use client";

import { ArrowLeftRight } from "lucide-react";
import { AnswerBlock } from "@/lib/api-client";
import ResponsePackageCard from "./ResponsePackageCard";

interface MultiAnswerCardProps {
  blocks: AnswerBlock[];
  comparison?: boolean;
  /** Timestamp to display on each answered block */
  timestamp?: string;
}

/**
 * Renders one chat-bubble response that contains multiple answers
 * (one per sub-question). Each block is shown separately and clearly
 * labelled; unanswered questions get an explicit "could not find" state
 * so every asked question is visibly accounted for.
 */
export default function MultiAnswerCard({
  blocks,
  comparison = false,
  timestamp,
}: MultiAnswerCardProps) {
  if (!blocks || blocks.length === 0) {
    return null;
  }

  return (
    <div className="w-full space-y-3">
      {comparison && (
        <div className="flex items-center gap-2">
          <ArrowLeftRight className="h-3.5 w-3.5 text-muted-foreground" />
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Comparison
          </h3>
          <div className="h-px flex-1 bg-border" />
        </div>
      )}

      {blocks.map((block, index) => (
        <AnswerBlockItem
          key={`${index}-${block.question}`}
          index={index}
          block={block}
          timestamp={timestamp}
        />
      ))}
    </div>
  );
}

function AnswerBlockItem({
  index,
  block,
  timestamp,
}: {
  index: number;
  block: AnswerBlock;
  timestamp?: string;
}) {
  const unanswered = block.routing === "no_answer" || block.excerpts.length === 0;

  if (unanswered) {
    return (
      <div className="rounded-lg border border-dashed border-border p-3">
        <p className="text-sm font-medium text-foreground">
          <span className="mr-2 text-muted-foreground">{index + 1}.</span>
          {block.question}
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          Could not find reliable information about &ldquo;{block.question}&rdquo;
          in the available knowledge base.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border p-3">
      <p className="mb-2 text-sm font-medium text-foreground">
        <span className="mr-2 text-muted-foreground">{index + 1}.</span>
        {block.question}
      </p>
      <ResponsePackageCard
        title={block.title}
        answerPhrase={block.answer_phrase}
        excerpts={block.excerpts}
        confidence={block.confidence}
        routing={block.routing}
        embedded
        timestamp={timestamp}
      />
    </div>
  );
}
