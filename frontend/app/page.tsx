"use client";

import { useState } from "react";
import { SearchBar, ResponsePackageCard, RelatedQuestions } from "@/components/search";
import { searchKnowledgeBase, SearchResponse } from "@/lib/api-client";
import { ThumbsFeedback } from "@/components/feedback";

export default function HomePage() {
  const [query, setQuery] = useState("");
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSearch = async (q: string) => {
    setQuery(q);
    setIsLoading(true);
    setError(null);

    try {
      const result = await searchKnowledgeBase(q);
      setResponse(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setIsLoading(false);
    }
  };

  const handleAskRelated = (question: string) => {
    handleSearch(question);
  };

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border py-4">
        <div className="max-w-4xl mx-auto px-4">
          <h1 className="text-2xl font-bold text-foreground">Hexta</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Mortgage Knowledge Assistant
          </p>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 py-8">
        {!response && !isLoading && (
          <div className="mt-12 text-center">
            <h2 className="text-3xl font-bold text-foreground mb-2">
              Ask me about mortgage lending
            </h2>
            <p className="text-muted-foreground mb-8 max-w-2xl mx-auto">
              I can help you find information about credit scores, LTV ratios,
              required documents, loan eligibility, and more — all from our
              internal knowledge base.
            </p>
          </div>
        )}

        <div className="mt-8">
          <SearchBar
            onSearch={handleSearch}
            isLoading={isLoading}
            placeholder="e.g., What is the minimum credit score for a VA loan?"
          />
        </div>

        {error && (
          <div className="mt-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-800 text-center">
            {error}
          </div>
        )}

        {response && (
          <>
            <ResponsePackageCard
              title={response.title}
              excerpts={response.excerpts}
              confidence={response.confidence}
              routing={response.routing}
            />
            <ThumbsFeedback responseId={response.response_id} />
            <RelatedQuestions
              questions={response.related_questions}
              onAskQuestion={handleAskRelated}
            />
          </>
        )}
      </main>

      <footer className="border-t border-border py-6 mt-12">
        <div className="max-w-4xl mx-auto px-4 text-center text-sm text-muted-foreground">
          Hexta — Mortgage Knowledge Assistant. All responses are sourced from
          internal documents.
        </div>
      </footer>
    </div>
  );
}
