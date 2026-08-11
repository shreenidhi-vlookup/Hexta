"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Search, Send, Loader2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  SpeechInput,
  SpeechInputRecordButton,
  SpeechInputCancelButton,
  type SpeechInputData,
} from "@/components/ui/speech-input";
import { BarVisualizer } from "@/components/ui/bar-visualizer";

interface SearchBarProps {
  onSearch: (query: string) => void;
  isLoading?: boolean;
  placeholder?: string;
}

export default function SearchBar({
  onSearch,
  isLoading = false,
  placeholder = "Ask about requirements...",
}: SearchBarProps) {
  const [query, setQuery] = useState("");
  const [isListening, setIsListening] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (
      typeof window !== "undefined" &&
      window.matchMedia("(pointer: coarse)").matches
    ) {
      return;
    }
    inputRef.current?.focus();
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = query.trim();
    if (trimmed && !isLoading) {
      onSearch(trimmed);
      setQuery("");
    }
  };

  const handleTranscriptChange = useCallback((data: SpeechInputData) => {
    setQuery(data.transcript);
  }, []);

  const handleSpeechStart = useCallback(() => {
    setIsListening(true);
    setQuery("");
  }, []);

  const handleSpeechStop = useCallback(
    (data: SpeechInputData) => {
      setIsListening(false);
      const transcript = data.transcript.trim();
      setQuery("");
      if (transcript) {
        onSearch(transcript);
      }
    },
    [onSearch]
  );

  const handleSpeechCancel = useCallback(() => {
    setIsListening(false);
    setQuery("");
  }, []);

  return (
    <form
      onSubmit={handleSubmit}
      className="relative mx-auto w-full max-w-3xl lg:max-w-4xl"
    >
      {isListening && (
        <div className="absolute bottom-full left-0 right-0 z-20 mb-3 rounded-xl border border-border bg-card p-3 shadow-md">
          <div className="flex items-center gap-3">
            <BarVisualizer
              demo
              state="listening"
              barCount={12}
              className="h-6 w-24 shrink-0"
            />
            <p className="min-w-0 flex-1 truncate text-sm text-foreground">
              {query.trim() || "Listening..."}
            </p>
          </div>
        </div>
      )}

      <div className="relative">
        <Input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={placeholder}
          disabled={isLoading || isListening}
          maxLength={500}
          aria-label="Ask about requirements"
          className="pl-12 pr-40 py-6 text-lg rounded-xl shadow-sm"
        />
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />

        <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
          <SpeechInput
            onChange={handleTranscriptChange}
            onStart={handleSpeechStart}
            onStop={handleSpeechStop}
            onCancel={handleSpeechCancel}
            size="lg"
          >
            <SpeechInputRecordButton />
            <SpeechInputCancelButton />
          </SpeechInput>
          <Button
            type="submit"
            size="icon"
            disabled={isLoading || !query.trim()}
            className="rounded-lg w-10 h-10"
            aria-label="Send message"
          >
            {isLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </Button>
        </div>
      </div>
    </form>
  );
}
