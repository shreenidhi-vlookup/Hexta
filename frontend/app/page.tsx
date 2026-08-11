"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  AlertCircle,
  LogOut,
  Sparkles,
  Copy,
  Volume2,
  RefreshCw,
  MoreVertical,
} from "lucide-react";
import { ResponsePackageCard, MultiAnswerCard, RelatedQuestions } from "@/components/search";
import SettingsDialog from "@/components/settings/SettingsDialog";
import ThemeToggle from "@/components/ui/theme-toggle";
import { searchKnowledgeBase, SearchResponse, getUserSettings } from "@/lib/api-client";
import { clearToken, getToken, getTokenRole, isAdminRole } from "@/lib/auth";
import ThumbsFeedback from "@/components/feedback/ThumbsFeedback";
import {
  listRecentChats,
  saveChat,
  deleteChat,
  newChatId,
  deriveTitle,
  type RecentChat,
  type ChatTurn,
} from "@/lib/conversations";
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
import { HomeSidebar } from "@/components/nav/HomeSidebar";
import type { AdminSection } from "@/components/nav/HomeSidebar";
import { AdminSections } from "@/components/admin/AdminPanel";

export type NavView = "chat" | AdminSection | "settings" | "help";

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

const SIDEBAR_STORAGE_KEY = "hexa-sidebar-collapsed";

export default function HomePage() {
  const router = useRouter();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAuthed, setIsAuthed] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [showSignOutDialog, setShowSignOutDialog] = useState(false);
  const [chatToDelete, setChatToDelete] = useState<RecentChat | null>(null);
  const [showRelatedQuestions, setShowRelatedQuestions] = useState(true);
  const [activeNav, setActiveNav] = useState<NavView>("chat");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem(SIDEBAR_STORAGE_KEY) === "true";
    }
    return false;
  });
  const [recentChats, setRecentChats] = useState<RecentChat[]>([]);
  const [currentChatId, setCurrentChatId] = useState<string | null>(null);
  const [latestResponseId, setLatestResponseId] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [sourceMenuOpen, setSourceMenuOpen] = useState(false);
  const messageIdRef = useRef(0);
  const submittingRef = useRef(false);
  const turnsRef = useRef<ChatTurn[]>([]);

  const isCurrentResponse = (m: ChatMessage) =>
    m.from === "assistant" && m.id === latestResponseId;

  const persistChat = useCallback(() => {
    if (!currentChatId) return;
    const turns = turnsRef.current;
    if (turns.length === 0) return;
    saveChat({
      id: currentChatId,
      title: deriveTitle(turns),
      createdAt: Date.now(),
      turns,
    });
    setRecentChats(listRecentChats());
  }, [currentChatId]);

  const appendTurn = useCallback(
    (turn: ChatTurn) => {
      turnsRef.current.push(turn);
      persistChat();
    },
    [persistChat],
  );

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
    if (!sidebarCollapsed) {
      setRecentChats(listRecentChats());
    }
  }, [sidebarCollapsed]);

  useEffect(() => {
    const token = getToken();
    setIsAuthed(Boolean(token));
    setIsAdmin(isAdminRole(getTokenRole(token ?? "")));
    setSidebarCollapsed(localStorage.getItem(SIDEBAR_STORAGE_KEY) === "true");
    if (token) {
      loadSettings();
      setRecentChats(listRecentChats());
    }
  }, [loadSettings]);

  useEffect(() => {
    if (!currentChatId && activeNav === "chat") {
      setCurrentChatId(newChatId());
    }
  }, [activeNav, currentChatId]);

  const handleNewChat = useCallback(() => {
    turnsRef.current = [];
    setCurrentChatId(newChatId());
    setMessages([]);
    setError(null);
    setLatestResponseId(null);
    setActiveNav("chat");
  }, []);

  const handleHome = useCallback(() => {
    setActiveNav("chat");
  }, []);

  const handleSelectRecent = useCallback((chat: RecentChat) => {
    turnsRef.current = [...chat.turns];
    setCurrentChatId(chat.id);
    const idRef = { current: 0 };
    const msgs: ChatMessage[] = chat.turns.map((t) => {
      const id = `r${++idRef.current}`;
      if (t.role === "user") {
        return { id, from: "user", query: t.content, timestamp: "" };
      }
      return { id, from: "assistant", text: t.content, timestamp: "" };
    });
    setMessages(msgs);
    setActiveNav("chat");
    setLatestResponseId(msgs.findLast((m) => m.from === "assistant")?.id ?? null);
  }, []);

  const handleRequestDeleteRecent = useCallback((chat: RecentChat) => {
    setChatToDelete(chat);
  }, []);

  const handleCancelDeleteRecent = useCallback(() => {
    setChatToDelete(null);
  }, []);

  const handleConfirmDeleteRecent = useCallback(() => {
    if (!chatToDelete) return;
    const id = chatToDelete.id;
    deleteChat(id);
    setRecentChats(listRecentChats());
    if (currentChatId === id) {
      turnsRef.current = [];
      setCurrentChatId(null);
      setMessages([]);
      setLatestResponseId(null);
      setError(null);
      setActiveNav("chat");
    }
    setChatToDelete(null);
  }, [chatToDelete, currentChatId]);

  const handleSidebarSelect = useCallback((view: NavView) => {
    if (view === "settings") {
      setSettingsOpen(true);
      setActiveNav("chat");
    } else if (view === "help") {
      setActiveNav("help");
    } else if (view === "chat") {
      setActiveNav("chat");
    } else {
      setActiveNav(view);
    }
  }, []);

  const handleLogout = useCallback(() => {
    clearToken();
    setIsAuthed(false);
    setIsAdmin(false);
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

    const ensureChat = () => {
      if (!currentChatId) setCurrentChatId(newChatId());
    };

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
      ensureChat();
      const nextId = ++messageIdRef.current;
      setMessages((prev) => [
        ...prev,
        { id: `m${nextId}`, from: "user", query: trimmed, timestamp: now() },
      ]);
      appendTurn({ role: "user", content: trimmed });
    }

    const canned = detectCannedReply(trimmed);
    if (canned) {
      const msgId = replaceMsgId ?? `m${++messageIdRef.current}`;
      if (replaceMsgId) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === replaceMsgId
              ? {
                  ...m,
                  from: "assistant" as const,
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
            id: msgId,
            from: "assistant" as const,
            text: canned.text,
            followUps: canned.followUps,
            isStreaming: false,
            streamedTitle: "",
            timestamp: now(),
          },
        ]);
      }
      setLatestResponseId(msgId);
      appendTurn({ role: "assistant", content: canned.text });
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
      setLatestResponseId(msgId);
      appendTurn({
        role: "assistant",
        content: result.answer_phrase || result.title,
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

  const handleToggleCollapse = useCallback(() => {
    const next = !sidebarCollapsed;
    setSidebarCollapsed(next);
    localStorage.setItem(SIDEBAR_STORAGE_KEY, String(next));
    if (next) {
      setRecentChats([]);
    } else {
      setRecentChats(listRecentChats());
    }
  }, [sidebarCollapsed]);

  const renderChatContent = () => (
    <>
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
                      <MessageAvatar src="" name="You" />
                      <MessageContent>{message.query}</MessageContent>
                      <span className="text-[10px] text-muted-foreground/50">
                        {message.timestamp || now()}
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
                      <div className="flex min-w-0 flex-1 flex-col items-start gap-1">
                        <MessageContent variant="contained">
                          {message.text ? (
                            <>
                              <div className="text-sm">{message.text}</div>
                              {message.followUps &&
                                message.followUps.length > 0 &&
                                isCurrentResponse(message) && (
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
                          ) : message.isStreaming ? (
                            message.streamedTitle ? (
                              <Response>{message.streamedTitle}</Response>
                            ) : (
                              <div className="text-sm text-muted-foreground">
                                Searching…
                              </div>
                            )
                          ) : message.response ? (
                            <>
                              {message.response.answers &&
                              message.response.answers.length > 1 ? (
                                <MultiAnswerCard
                                  blocks={message.response.answers}
                                  comparison={message.response.comparison}
                                  timestamp={message.timestamp}
                                  sourcesOpen={sourcesOpen}
                                  onToggleSources={() =>
                                    setSourcesOpen((open) => !open)
                                  }
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
                                  sourcesOpen={sourcesOpen}
                                  onToggleSources={() =>
                                    setSourcesOpen((open) => !open)
                                  }
                                />
                              )}
                            </>
                          ) : (
                            <div className="text-muted-foreground text-sm">
                              {message.error ?? "Something went wrong"}
                            </div>
                          )}
                        </MessageContent>
                        {message.response &&
                          isCurrentResponse(message) &&
                          message.response.routing !== "no_answer" && (
                            <div className="flex items-center gap-1 mt-1">
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                className="h-8 w-8 p-0 text-muted-foreground hover:text-foreground"
                                onClick={() => {
                                  const phrases = answerPhrases(message.response);
                                  if (phrases.length > 0) {
                                    const utterance =
                                      new SpeechSynthesisUtterance(
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
                                className="h-8 w-8 p-0 text-muted-foreground hover:text-foreground"
                                onClick={() => {
                                  const phrases = answerPhrases(message.response);
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
                              <ThumbsFeedback
                                responseId={message.response.response_id}
                                compact
                              />
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                className="h-8 w-8 p-0 text-muted-foreground hover:text-foreground"
                                onClick={() => {
                                  if (message.query) {
                                    handleSearch(message.query, message.id);
                                  }
                                }}
                                aria-label="Regenerate answer"
                              >
                                <RefreshCw className="h-3.5 w-3.5" />
                              </Button>
                              <DropdownMenu
                                open={sourceMenuOpen}
                                onOpenChange={setSourceMenuOpen}
                              >
                                <DropdownMenuTrigger asChild>
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    className="h-8 w-8 p-0 text-muted-foreground hover:text-foreground"
                                    aria-label="Source options"
                                  >
                                    <MoreVertical className="h-3.5 w-3.5" />
                                  </Button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="end" side="bottom">
                                  <DropdownMenuItem
                                    onClick={() => {
                                      setSourcesOpen((open) => !open);
                                      setSourceMenuOpen(false);
                                    }}
                                  >
                                    {sourcesOpen
                                      ? "Hide sources"
                                      : "View sources"}
                                  </DropdownMenuItem>
                                </DropdownMenuContent>
                              </DropdownMenu>
                            </div>
                          )}
                        {showRelatedQuestions &&
                          isCurrentResponse(message) &&
                          message.response?.routing !== "no_answer" && (
                            <RelatedQuestions
                              questions={message.response?.related_questions ?? []}
                              onAskQuestion={handleAskRelated}
                            />
                          )}
                        <span className="text-[10px] text-muted-foreground/50">
                          {message.timestamp || now()}
                        </span>
                      </div>
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
            <div className="mt-4 text-center text-xs text-muted-foreground">
              Responses are sourced verbatim from internal documents.
            </div>
          )}
        </div>
      </footer>
    </>
  );

  return (
    <div className="flex h-screen bg-background text-foreground">
      {isAuthed && (
        <HomeSidebar
          collapsed={sidebarCollapsed}
          onToggleCollapse={handleToggleCollapse}
          isAdmin={isAdmin}
          active={activeNav}
          onSelect={handleSidebarSelect}
          onNewChat={handleNewChat}
          onHome={handleHome}
          recent={recentChats}
          onSelectRecent={handleSelectRecent}
          onDeleteRecent={handleRequestDeleteRecent}
        />
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="border-b border-border bg-card/50 backdrop-blur-sm sticky top-0 z-10">
          <div className="mx-auto max-w-4xl flex h-16 items-center justify-between px-4 lg:max-w-6xl xl:max-w-7xl">
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
            <div className="flex items-center gap-2">
              <ThemeToggle />
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
          </div>
        </header>

        {activeNav === "chat" ? (
          renderChatContent()
        ) : activeNav === "help" ? (
          <div className="flex-1 overflow-y-auto p-6">
            <div className="mx-auto max-w-3xl space-y-4">
              <h2 className="text-xl font-bold">Help</h2>
              <p className="text-sm text-muted-foreground">
                Hexta is a retrieval-based knowledge assistant. Ask questions
                about credit scores, LTV ratios, required documents, eligibility
                criteria, mortgage terms, and property management processes.
              </p>
              <ul className="list-disc pl-5 text-sm text-muted-foreground space-y-1">
                <li>Answers are sourced verbatim from internal documents.</li>
                <li>
                  Responses include a confidence score and a routing label
                  (answer/partial/no_answer).
                </li>
                <li>
                  Click &quot;View sources&quot; to see where an answer came from.
                </li>
                <li>
                  Use the sidebar to switch to administration tools (admin
                  roles only).
                </li>
              </ul>
            </div>
          </div>
        ) : (
          <AdminSections active={activeNav as AdminSection} />
        )}
      </div>

      <SettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        onShowRelatedQuestionsChange={setShowRelatedQuestions}
      />

      <AlertDialog
        open={chatToDelete !== null}
        onOpenChange={(open) => {
          if (!open) setChatToDelete(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete recent chat?</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete this session? This action will
              remove the chat from your recent chats.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={handleCancelDeleteRecent}>
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction onClick={handleConfirmDeleteRecent}>
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

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
