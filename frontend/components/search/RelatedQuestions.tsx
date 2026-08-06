"use client";

import { HelpCircle } from "lucide-react";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";

interface RelatedQuestionsProps {
  questions: string[];
  onAskQuestion?: (question: string) => void;
}

export default function RelatedQuestions({
  questions,
  onAskQuestion,
}: RelatedQuestionsProps) {
  if (!questions || questions.length === 0) return null;

  return (
    <div className="mt-6 border-t border-border pt-4">
      <Accordion type="single" collapsible defaultValue="related">
        <AccordionItem value="related" className="border-none">
          <AccordionTrigger className="text-sm font-medium text-muted-foreground hover:text-foreground hover:no-underline">
            Related Questions ({questions.length})
          </AccordionTrigger>
          <AccordionContent className="pb-0">
            <div className="space-y-2 pt-2">
              {questions.map((q, i) => (
                <Button
                  key={i}
                  type="button"
                  variant="ghost"
                  onClick={() => onAskQuestion?.(q)}
                  className="flex h-auto w-full items-start justify-start gap-2.5 rounded-lg border border-dashed border-border bg-background px-3 py-2.5 text-left text-sm text-wrap text-foreground hover:bg-accent"
                >
                  <HelpCircle className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                  {q}
                </Button>
              ))}
            </div>
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </div>
  );
}
