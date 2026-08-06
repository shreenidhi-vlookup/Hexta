"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { AlertCircle, LogOut, Sparkles, Copy, Volume2, RefreshCw, Settings2 } from "lucide-react";
import { ResponsePackageCard, MultiAnswerCard, RelatedQuestions } from "@/components/search";
import SettingsDialog from "@/components/settings/SettingsDialog";
import { searchKnowledgeBase, SearchResponse, getUserSettings } from "@/lib/api-client";
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
import SearchBar from "@/components/search/SearchBar";
import { detectCannedReply } from "@/lib/greetings";
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
} from "@/components/ui/conversation";
import {
  Message,
  MessageAvatar,
  MessageContent,
} from "@/components/ui/message";
import { Orb } from "@/components/ui/orb";
import { Response } from "@/components/ui/response";
import { Matrix, loader } from "@/components/ui/matrix";

interface ChatMessage {
  id: string;
  from: "user" | "assistant";
  query?: string;
  response?: SearchResponse;
  text?: string;
  followUps?: string[];
  error?: string;
  streamedTitle?: string;
  isStreaming?: boolean;
  timestamp: string;
}

function answerPhrases(response?: SearchResponse): string[] {
  if (!response) return [];
  if (response.answers && response.answers.length > 1) {
    return response.answers
      .map((a) => a.answer_phrase)
      .filter(Boolean);
  }
  return response.answer_phrase ? [response.answer_phrase] : [];
}

export default function HomePage() {
  const router = useRouter();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAuthed, setIsAuthed] = useState(false);
  const [showSignOutDialog, setShowSignOutDialog] = useState(false);
  const [showRelatedQuestions, setShowRelatedQuestions] = useState(true);
  const messageIdRef = useRef(0);
  const submittingRef = useRef(false);

  const buildHistory = useCallback((msgs: ChatMessage[]) => {
    const turns: { question: string; answer?: string }[] = [];
    for (const m of msgs) {
      if (m.from === "user" && m.query) {
        turns.push({ question: m.query });
      } else if (m.from === "assistant" && m.response && turns.length > 0) {
        const last = turns[turns.length - 1];
        if (!last.answer && m.response.answer_phrase) {
          last.answer = m.response.answer_phrase;
        }
      }
    }
    return turns.slice(-4);
  }, []);

  const loadSettings = useCallback(async () => {
    try {
      const token = getToken() ?? undefined;
      const settings = await getUserSettings(token);
      setShowRelatedQuestions(settings.show_related_questions);
    } catch {
      setShowRelatedQuestions(true);
    }
  }, []);

  useEffect(() => {
    setIsAuthed(Boolean(getToken()));
    loadSettings();
  }, [loadSettings]);

  const handleLogout = useCallback(() => {
    clearToken();
    setIsAuthed(false);
    setMessages([]);
    setError(null);
    setShowSignOutDialog(false);
    router.push("/login");
  }, [router]);

  const now = () =>
    new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  const handleSearch = async (q: string, replaceMsgId?: string) => {
    const trimmed = q.trim();
    if (!trimmed || isLoading || submittingRef.current) return;
    submittingRef.current = true;

    if (replaceMsgId) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === replaceMsgId
            ? {
                ...m,
                response: undefined,
                text: undefined,
                followUps: undefined,
                error: undefined,
                isStreaming: true,
                streamedTitle: "",
              }
            : m
        )
      );
    } else {
      const nextId = ++messageIdRef.current;
      setMessages((prev) => [
        ...prev,
        { id: `m${nextId}`, from: "user", query: trimmed, timestamp: now() },
      ]);
    }

    const canned = detectCannedReply(trimmed);
    if (canned) {
      if (replaceMsgId) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === replaceMsgId
              ? {
                  ...m,
                  from: "assistant",
                  text: canned.text,
                  followUps: canned.followUps,
                  isStreaming: false,
                  streamedTitle: "",
                  timestamp: now(),
                }
              : m
          )
        );
      } else {
        setMessages((prev) => [
          ...prev,
          {
            id: `m${++messageIdRef.current}`,
            from: "assistant",
            text: canned.text,
            followUps: canned.followUps,
            timestamp: now(),
          },
        ]);
      }
      submittingRef.current = false;
      return;
    }

    setError(null);
    setIsLoading(true);

    const attach = (id: string, patch: Partial<ChatMessage>) =>
      setMessages((prev) =>
        prev.some((m) => m.id === id)
          ? prev.map((m) => (m.id === id ? { ...m, ...patch } : m))
          : [
              ...prev,
              {
                id,
                from: "assistant" as const,
                query: trimmed,
                timestamp: now(),
                ...patch,
              },
            ]
      );

    try {
      const token = getToken() ?? undefined;
      const history = buildHistory(messages);
      const result = await searchKnowledgeBase(trimmed, token, history);
      const msgId = replaceMsgId ?? `m${++messageIdRef.current}`;
      attach(msgId, {
        response: result,
        streamedTitle: "",
        isStreaming: true,
      });
      let currentTitle = "";
      const titleChars = result.title.split("");
      const streamInterval = setInterval(() => {
        if (currentTitle.length < titleChars.length) {
          currentTitle += titleChars[currentTitle.length];
          attach(msgId, { streamedTitle: currentTitle });
        } else {
          clearInterval(streamInterval);
          attach(msgId, { isStreaming: false });
        }
      }, 30);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Something went wrong";
      setError(message);
      if (replaceMsgId) {
        attach(replaceMsgId, { error: message, isStreaming: false });
      }
    } finally {
      submittingRef.current = false;
      setIsLoading(false);
    }
  };

  const handleAskRelated = (question: string) => {
    handleSearch(question);
  };

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <header className="border-b border-border bg-card/50 backdrop-blur-sm sticky top-0 z-10">
        <div className="mx-auto max-w-4xl px-4 h-16 flex items-center justify-between lg:max-w-6xl xl:max-w-7xl">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-primary text-primary-foreground shadow-sm">
              <Sparkles className="w-5 h-5" />
            </div>
            <div className="leading-tight">
              <h1 className="text-2xl font-bold text-foreground">Hexta</h1>
              <p className="text-xs text-muted-foreground">
                Knowledge Assistant
              </p>
            </div>
          </div>
          {isAuthed ? (
            <div className="flex items-center gap-2">
              <SettingsDialog />
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setShowSignOutDialog(true)}
              >
                <LogOut className="h-4 w-4 mr-2" />
                Sign out
              </Button>
            </div>
          ) : (
            <Button asChild size="sm">
              <Link href="/login">Sign in</Link>
            </Button>
          )}
        </div>
      </header>

      <Conversation className="flex-1">
        <ConversationContent className="mx-auto w-full max-w-4xl px-4 lg:max-w-6xl xl:max-w-7xl">
          {messages.length === 0 ? (
            <ConversationEmptyState
              icon={
                <div className="p-3 rounded-full bg-primary/10">
                  <Sparkles className="w-6 h-6 text-primary" />
                </div>
              }
              title="Ask me about requirements"
              description="I can help you find information about credit scores, LTV ratios, required documents, eligibility criteria, and more — all from our internal knowledge base."
            />
          ) : (
            <>
              {messages.map((message) => (
                <Message key={message.id} from={message.from}>
                  {message.from === "user" ? (
                    <>
                      <MessageContent>{message.query}</MessageContent>
                      <MessageAvatar src="" name="You" />
                      <span className="text-[10px] text-muted-foreground/50">
                        {message.timestamp}
                      </span>
                    </>
                  ) : (
                    <>
                      {message.isStreaming ? (
                        <div className="ring-border size-8 overflow-hidden rounded-full ring-1">
                          <Orb agentState="talking" className="h-full w-full" />
                        </div>
                      ) : (
                        <MessageAvatar src="" name="Hexta" />
                      )}
                      <MessageContent
                        variant="flat"
                        className="max-w-full w-full"
                      >
                        {message.text ? (
                          <>
                            <div className="text-sm">{message.text}</div>
                            {message.followUps &&
                              message.followUps.length > 0 && (
                                <div className="flex flex-wrap gap-2 pt-1">
                                  {message.followUps.map((f) => (
                                    <Button
                                      key={f}
                                      type="button"
                                      variant="outline"
                                      size="sm"
                                      className="h-auto text-xs"
                                      onClick={() => handleAskRelated(f)}
                                    >
                                      {f}
                                    </Button>
                                  ))}
                                </div>
                              )}
                          </>
                        ) : message.isStreaming && message.streamedTitle ? (
                          <Response>{message.streamedTitle}</Response>
                        )                         : message.response ? (
                          <>
                            {message.response.answers &&
                            message.response.answers.length > 1 ? (
                              <MultiAnswerCard
                                blocks={message.response.answers}
                                comparison={message.response.comparison}
                                timestamp={message.timestamp}
                              />
                            ) : (
                              <ResponsePackageCard
                                title={message.response.title}
                                answerPhrase={message.response.answer_phrase}
                                excerpts={message.response.excerpts}
                                confidence={message.response.confidence}
                                routing={message.response.routing}
                                embedded
                                timestamp={message.timestamp}
                              />
                            )}
                            {message.response.routing !== "no_answer" && (
                              <div className="flex items-center gap-1 mt-1">
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="sm"
                                  className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
                                  onClick={() => {
                                    const phrases = answerPhrases(
                                      message.response,
                                    );
                                    if (phrases.length > 0) {
                                      const utterance = new SpeechSynthesisUtterance(
                                        phrases.join(". "),
                                      );
                                      window.speechSynthesis.speak(utterance);
                                    }
                                  }}
                                  aria-label="Speak answer"
                                >
                                  <Volume2 className="h-3.5 w-3.5" />
                                </Button>
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="sm"
                                  className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
                                  onClick={() => {
                                    const phrases = answerPhrases(
                                      message.response,
                                    );
                                    if (phrases.length > 0) {
                                      navigator.clipboard.writeText(
                                        phrases.join(". "),
                                      );
                                    }
                                  }}
                                  aria-label="Copy answer"
                                >
                                  <Copy className="h-3.5 w-3.5" />
                                </Button>
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="sm"
                                  className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
                                  onClick={() => {
                                    if (message.query) {
                                      handleSearch(message.query, message.id);
                                    }
                                  }}
                                  aria-label="Regenerate answer"
                                >
                                  <RefreshCw className="h-3.5 w-3.5" />
                                </Button>
                              </div>
                            )}
                            {message.response.routing !== "no_answer" && (
                              <ThumbsFeedback
                                responseId={message.response.response_id}
                              />
                            )}
                            {showRelatedQuestions &&
                              message.response.routing !== "no_answer" && (
                              <RelatedQuestions
                                questions={message.response.related_questions}
                                onAskQuestion={handleAskRelated}
                              />
                            )}
                          </>
                        ) : message.isStreaming ? (
                          <div className="text-sm text-muted-foreground">
                            Searching…
                          </div>
                        ) : (
                          <div className="text-muted-foreground text-sm">
                            {message.error ?? "Something went wrong"}
                          </div>
                        )}
                      </MessageContent>
                    </>
                  )}
                </Message>
              ))}

              {isLoading && (
                <Message from="assistant">
                  <MessageAvatar src="" name="Hexta" />
                  <MessageContent
                    variant="flat"
                    className="items-center gap-3 flex-row"
                  >
                    <Matrix
                      rows={7}
                      cols={7}
                      frames={loader}
                      size={3}
                      gap={1}
                      ariaLabel="Searching"
                    />
                    <span className="text-sm text-muted-foreground">
                      Searching knowledge base…
                    </span>
                  </MessageContent>
                </Message>
              )}

              {error && (
                <Alert variant="destructive" className="mt-4">
                  <AlertCircle className="h-4 w-4" />
                  <AlertTitle>Search failed</AlertTitle>
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}
            </>
          )}
        </ConversationContent>

        <ConversationScrollButton />
      </Conversation>

      <footer className="border-t border-border bg-card/50 backdrop-blur-sm sticky bottom-0 z-10">
        <div className="mx-auto max-w-4xl px-4 py-4 lg:max-w-6xl xl:max-w-7xl">
          <SearchBar onSearch={handleSearch} isLoading={isLoading} />
          {messages.length === 0 && (
            <div className="mt-3 text-center text-xs text-muted-foreground">
              Responses are sourced verbatim from internal documents.
            </div>
          )}
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
