"use client";

import { BookOpen, FileText, Hash, MoreVertical } from "lucide-react";
import { SearchExcerpt } from "@/lib/api-client";
import ConfidenceBadge from "./ConfidenceBadge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { useState } from "react";

interface ResponsePackageCardProps {
  title: string;
  answerPhrase: string;
  excerpts: SearchExcerpt[];
  confidence: number;
  routing: "answer" | "partial" | "no_answer";
  /** Compact layout for use inside chat bubbles */
  embedded?: boolean;
  /** Timestamp to display */
  timestamp?: string;
}

export default function ResponsePackageCard({
  title,
  answerPhrase,
  excerpts,
  confidence,
  routing,
  embedded = false,
  timestamp,
}: ResponsePackageCardProps) {
  const [sourcesOpen, setSourcesOpen] = useState(false);

  if (routing === "no_answer" || excerpts.length === 0) {
    return (
      <Card className="max-w-4xl mx-auto mt-8 shadow-sm text-center">
        <CardContent className="p-8">
          <h3 className="text-lg font-semibold text-foreground mb-2">
            No answer found
          </h3>
          <p className="text-muted-foreground">
            I could not find a reliable answer to this question in the
            available knowledge base.
          </p>
          <ul className="mt-4 inline-block text-left text-sm text-muted-foreground space-y-1.5">
            <li>• Rephrase your question using different words</li>
            <li>
              • Use more specific keywords (e.g. &quot;credit score&quot; instead of &quot;score&quot;)
            </li>
            <li>• Ask about a supported topic, like requirements or eligibility</li>
          </ul>
        </CardContent>
      </Card>
    );
  }

  if (embedded) {
    return (
      <div className="space-y-2 w-full">
        <div className="flex items-start justify-between gap-2">
          <p className="text-sm text-foreground leading-relaxed flex-1">
            {answerPhrase || title}
          </p>
          <div className="flex items-center gap-2 flex-shrink-0">
            {timestamp && (
              <span className="text-[10px] text-muted-foreground/60">
                {timestamp}
              </span>
            )}
            {excerpts.length > 0 && (
              <DropdownMenu
                open={sourcesOpen}
                onOpenChange={setSourcesOpen}
              >
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-6 w-6 p-0"
                    aria-label="More options"
                  >
                    <MoreVertical className="h-3.5 w-3.5" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" side="bottom">
                  <DropdownMenuItem
                    onClick={() => setSourcesOpen(!sourcesOpen)}
                  >
                    {sourcesOpen
                      ? "Hide sources"
                      : `View sources (${excerpts.length})`}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
        </div>

        {sourcesOpen && (
          <div className="space-y-3 pt-2">
            <div className="flex items-center gap-2">
              <BookOpen className="h-3.5 w-3.5 text-muted-foreground" />
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Sources ({excerpts.length})
              </h3>
              <div className="h-px flex-1 bg-border" />
            </div>
            {excerpts.map((excerpt, i) => (
              <Card key={i} className="shadow-sm">
                <CardHeader className="pb-2 flex-row items-start gap-2 space-y-0">
                  <div className="mt-0.5 flex-shrink-0 text-muted-foreground">
                    {excerpt.source.chunk_type === "table" ? (
                      <Hash className="h-3 w-3" />
                    ) : (
                      <FileText className="h-3 w-3" />
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <CardTitle className="text-xs font-semibold leading-snug">
                      Source {i + 1}: {excerpt.source.title}
                    </CardTitle>
                    {excerpt.source.section && (
                      <p className="mt-0.5 text-[11px] text-muted-foreground">
                        {excerpt.source.section}
                      </p>
                    )}
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="prose prose-xs max-w-none">
                    {excerpt.text.split("\n").map((line, j) => (
                      <p key={j} className="mb-1.5 leading-relaxed">
                        {line}
                      </p>
                    ))}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto mt-8 space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h2 className="text-2xl font-bold text-foreground">{title}</h2>
        <div className="flex items-center gap-2">
          {timestamp && (
            <span className="text-[10px] text-muted-foreground/60">
              {timestamp}
            </span>
          )}
          <ConfidenceBadge confidence={confidence} routing={routing} size="sm" />
          {excerpts.length > 0 && (
            <DropdownMenu open={sourcesOpen} onOpenChange={setSourcesOpen}>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-6 w-6 p-0"
                  aria-label="More options"
                >
                  <MoreVertical className="h-3.5 w-3.5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" side="bottom">
                <DropdownMenuItem
                  onClick={() => setSourcesOpen(!sourcesOpen)}
                >
                  {sourcesOpen ? "Hide sources" : `View sources (${excerpts.length})`}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </div>

      {sourcesOpen && (
        <div className="space-y-3 pt-2">
          <div className="flex items-center gap-2">
            <BookOpen className="h-3.5 w-3.5 text-muted-foreground" />
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Sources ({excerpts.length})
            </h3>
            <div className="h-px flex-1 bg-border" />
          </div>
          {excerpts.map((excerpt, i) => (
            <Card key={i} className="shadow-sm">
              <CardHeader className="pb-2 flex-row items-start gap-2 space-y-0">
                <div className="mt-0.5 flex-shrink-0 text-muted-foreground">
                  {excerpt.source.chunk_type === "table" ? (
                    <Hash className="h-3 w-3" />
                  ) : (
                    <FileText className="h-3 w-3" />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <CardTitle className="text-xs font-semibold leading-snug">
                    Source {i + 1}: {excerpt.source.title}
                  </CardTitle>
                  {excerpt.source.section && (
                    <p className="mt-0.5 text-[11px] text-muted-foreground">
                      {excerpt.source.section}
                    </p>
                  )}
                </div>
              </CardHeader>
              <CardContent>
                <div className="prose prose-xs max-w-none">
                  {excerpt.text.split("\n").map((line, j) => (
                    <p key={j} className="mb-1.5 leading-relaxed">
                      {line}
                    </p>
                  ))}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}