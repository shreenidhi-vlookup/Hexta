"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { AlertCircle, LogOut } from "lucide-react";
import { SearchBar, ResponsePackageCard, RelatedQuestions } from "@/components/search";
import { searchKnowledgeBase, SearchResponse } from "@/lib/api-client";
import { clearToken, getToken } from "@/lib/auth";
import ThumbsFeedback from "@/components/feedback/ThumbsFeedback";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

export default function HomePage() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAuthed, setIsAuthed] = useState(false);
  const [showSignOutDialog, setShowSignOutDialog] = useState(false);

  useEffect(() => {
    setIsAuthed(Boolean(getToken()));
  }, []);

  const handleLogout = useCallback(() => {
    clearToken();
    setIsAuthed(false);
    setResponse(null);
    setQuery("");
    setError(null);
    setShowSignOutDialog(false);
    router.push("/login");
  }, [router]);

  const handleSearch = async (q: string) => {
    setQuery(q);
    setIsLoading(true);
    setError(null);

    try {
      const token = getToken() ?? undefined;
      const result = await searchKnowledgeBase(q, token);
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
        <div className="max-w-4xl mx-auto px-4 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-foreground">Hexta</h1>
            <p className="text-sm text-muted-foreground mt-1">
              Knowledge Assistant
            </p>
          </div>
          {isAuthed ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => setShowSignOutDialog(true)}
            >
              <LogOut className="h-4 w-4" />
              Sign out
            </Button>
          ) : (
            <Button asChild>
              <Link href="/login">Sign in</Link>
            </Button>
          )}
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 py-8">
        {!response && !isLoading && (
          <Card className="mt-12 text-center shadow-sm">
            <CardContent className="p-10">
              <h2 className="text-3xl font-bold text-foreground mb-2">
                Ask me about requirements
              </h2>
              <p className="text-muted-foreground mb-8 max-w-2xl mx-auto">
                I can help you find information about credit scores, LTV ratios,
                required documents, eligibility criteria, and more — all from
                our internal knowledge base. Enter your question below to get started.
              </p>
            </CardContent>
          </Card>
        )}

        <div className="mt-8">
          <SearchBar
            onSearch={handleSearch}
            isLoading={isLoading}
            placeholder="e.g., What is the minimum credit score for a VA loan?"
          />
        </div>

        {error && (
          <Alert variant="destructive" className="mt-6">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Search failed</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
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
          Hexta — Knowledge Assistant. All responses are sourced from
          internal documents.
        </div>
      </footer>

      <AlertDialog open={showSignOutDialog} onOpenChange={setShowSignOutDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Are you sure you want to sign out?</AlertDialogTitle>
            <AlertDialogDescription>
              You&apos;ll need to sign in again to search the knowledge base.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleLogout}>Sign out</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
