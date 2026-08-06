"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Search, Loader2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  SpeechInput,
  SpeechInputRecordButton,
  SpeechInputPreview,
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
    inputRef.current?.focus();
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = query.trim();
    if (trimmed && !isLoading) {
      onSearch(trimmed);
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
      if (transcript) {
        setQuery(transcript);
        onSearch(transcript);
      }
    },
    [onSearch]
  );

  const handleSpeechCancel = useCallback(() => {
    setIsListening(false);
  }, []);

  return (
    <form
      onSubmit={handleSubmit}
      className="relative mx-auto w-full max-w-3xl lg:max-w-4xl"
    >
      <div className="relative">
        <Input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={placeholder}
          disabled={isLoading || isListening}
          maxLength={500}
          className="pl-12 pr-40 py-6 text-lg rounded-xl shadow-sm"
        />
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />

        {isListening && (
          <BarVisualizer
            demo
            state="listening"
            barCount={9}
            className="absolute inset-x-2 bottom-1.5 h-7 rounded-md bg-transparent p-0 items-end"
          />
        )}

        <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
          <SpeechInput
            onChange={handleTranscriptChange}
            onStart={handleSpeechStart}
            onStop={handleSpeechStop}
            onCancel={handleSpeechCancel}
            size="lg"
          >
            <SpeechInputPreview placeholder="Listening..." />
            <SpeechInputRecordButton />
            <SpeechInputCancelButton />
          </SpeechInput>
          <Button
            type="submit"
            size="icon"
            disabled={isLoading || !query.trim()}
            className="rounded-lg w-10 h-10"
            aria-label="Search"
          >
            {isLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Search className="w-4 h-4" />
            )}
          </Button>
        </div>
      </div>
    </form>
  );
}
