"use client";

import { SearchExcerpt } from "@/lib/api-client";
import ConfidenceBadge from "./ConfidenceBadge";
import SourceCitation from "./SourceCitation";

interface ResponsePackageCardProps {
  title: string;
  excerpts: SearchExcerpt[];
  confidence: number;
  routing: "answer" | "partial" | "no_answer";
}

export default function ResponsePackageCard({
  title,
  excerpts,
  confidence,
  routing,
}: ResponsePackageCardProps) {
  if (routing === "no_answer" || excerpts.length === 0) {
    return (
      <div className="max-w-4xl mx-auto mt-8 p-8 bg-card border border-border rounded-xl shadow-sm text-center">
        <h3 className="text-lg font-semibold text-foreground mb-2">
          No Answer Found
        </h3>
        <p className="text-muted-foreground">
          I couldn't find information matching your query in the knowledge base.
          Try rephrasing or asking about a different topic.
        </p>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto mt-8 space-y-6">
      <div className="flex items-start justify-between">
        <h2 className="text-2xl font-bold text-foreground">{title}</h2>
        <ConfidenceBadge confidence={confidence} routing={routing} />
      </div>

      <div className="space-y-4">
        {excerpts.map((excerpt, i) => (
          <div
            key={i}
            className="p-6 bg-card border border-border rounded-xl shadow-sm"
          >
            <div className="prose prose-sm max-w-none">
              {excerpt.text.split("\n").map((line, j) => (
                <p key={j} className="mb-2 leading-relaxed">
                  {line}
                </p>
              ))}
            </div>
            <div className="mt-4 pt-3 border-t border-border">
              <SourceCitation
                title={excerpt.source.title}
                section={excerpt.source.section}
                chunkType={excerpt.source.chunk_type}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
