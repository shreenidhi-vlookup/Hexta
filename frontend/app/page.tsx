"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { AlertCircle, LogOut, Search, Sparkles } from "lucide-react";
import { ResponsePackageCard, RelatedQuestions } from "@/components/search";
import { searchKnowledgeBase, SearchResponse } from "@/lib/api-client";
import { clearToken, getToken } from "@/lib/auth";
import ThumbsFeedback from "@/components/feedback/ThumbsFeedback";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import HeroSection from "@/components/home/HeroSection";
import SearchBar from "@/components/search/SearchBar";

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

  const handleClearSearch = () => {
    setResponse(null);
    setQuery("");
    setError(null);
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border bg-card/50 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-4xl mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-primary text-primary-foreground">
              <Sparkles className="w-4 h-4" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-foreground">Hexta</h1>
              <p className="text-xs text-muted-foreground -mt-0.5">
                Knowledge Assistant
              </p>
            </div>
          </div>
          {isAuthed ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setShowSignOutDialog(true)}
            >
              <LogOut className="h-4 w-4 mr-2" />
              Sign out
            </Button>
          ) : (
            <Button asChild size="sm">
              <Link href="/login">Sign in</Link>
            </Button>
          )}
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 py-8 pb-24">
        {!response && !isLoading && !error && (
          <HeroSection onSearch={handleSearch} />
        )}

        {error && (
          <Alert variant="destructive" className="mt-8 mx-auto max-w-2xl">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Search failed</AlertTitle>
            <AlertDescription>
              {error}
              <Button
                variant="link"
                size="sm"
                onClick={handleClearSearch}
                className="ml-2 p-0 h-auto text-inherit underline"
              >
                Try again
              </Button>
            </AlertDescription>
          </Alert>
        )}

        <div className="mt-8">
          <SearchBar
            onSearch={handleSearch}
            isLoading={isLoading}
            placeholder="e.g., What is the minimum credit score for a VA loan?"
          />
        </div>

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

        {!response && !isLoading && !error && (
          <div className="mt-16 text-center">
            <p className="text-xs text-muted-foreground">
              Responses are sourced verbatim from internal documents.
            </p>
          </div>
        )}
      </main>

      <footer className="border-t border-border py-4">
        <div className="max-w-4xl mx-auto px-4 text-center text-xs text-muted-foreground">
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
