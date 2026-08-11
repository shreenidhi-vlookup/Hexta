"use client"

import { useCallback, useEffect, useRef, useState } from "react"

export type SpeechStatus =
  | "idle"
  | "starting"
  | "listening"
  | "error"

export interface TranscriptSegment {
  id: string
  text: string
  timestamp: number
  isFinal: boolean
}

export interface SpeechRecognitionCallbacks {
  onPartialTranscript?: (data: { text: string }) => void
  onCommittedTranscript?: (data: { text: string }) => void
  onStart?: () => void
  onStop?: () => void
  onError?: (error: Error) => void
}

export interface UseSpeechRecognitionOptions extends SpeechRecognitionCallbacks {
  /** BCP-47 language code, e.g. "en-US" */
  lang?: string
  /** Keep listening continuously instead of stopping after a pause */
  continuous?: boolean
  /** Emit partial (interim) transcripts while speaking */
  interimResults?: boolean
}

interface SpeechRecognitionLike {
  lang: string
  continuous: boolean
  interimResults: boolean
  maxAlternatives: number
  start: () => void
  stop: () => void
  abort: () => void
  onstart: (() => void) | null
  onend: (() => void) | null
  onerror: ((event: { error: string }) => void) | null
  onresult: ((event: {
    resultIndex: number
    results: {
      length: number
      [i: number]: {
        isFinal: boolean
        [j: number]: { transcript: string }
      }
    }
  }) => void) | null
}

interface SpeechRecognitionConstructor {
  new (): SpeechRecognitionLike
}

function getSpeechRecognitionConstructor():
  | SpeechRecognitionConstructor
  | undefined {
  if (typeof window === "undefined") return undefined
  const w = window as Window & {
    SpeechRecognition?: SpeechRecognitionConstructor
    webkitSpeechRecognition?: SpeechRecognitionConstructor
  }
  return w.SpeechRecognition || w.webkitSpeechRecognition
}

export function useSpeechRecognition(
  options: UseSpeechRecognitionOptions = {}
) {
  const {
    lang = "en-US",
    continuous = false,
    interimResults = true,
    onPartialTranscript,
    onCommittedTranscript,
    onStart,
    onStop,
    onError,
  } = options

  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const [status, setStatus] = useState<SpeechStatus>("idle")
  const [partialTranscript, setPartialTranscript] = useState("")
  const [committedTranscripts, setCommittedTranscripts] = useState<
    TranscriptSegment[]
  >([])
  const [error, setError] = useState<string | null>(null)

  const callbacksRef = useRef({
    onPartialTranscript,
    onCommittedTranscript,
    onStart,
    onStop,
    onError,
  })
  useEffect(() => {
    callbacksRef.current = {
      onPartialTranscript,
      onCommittedTranscript,
      onStart,
      onStop,
      onError,
    }
  }, [onPartialTranscript, onCommittedTranscript, onStart, onStop, onError])

  const supported =
    typeof window !== "undefined" &&
    Boolean(getSpeechRecognitionConstructor())

  const getRecognition = useCallback((): SpeechRecognitionLike | null => {
    if (recognitionRef.current) return recognitionRef.current

    const Ctor = getSpeechRecognitionConstructor()
    if (!Ctor) return null

    const recognition = new Ctor()
    recognition.lang = lang
    recognition.continuous = continuous
    recognition.interimResults = interimResults
    recognition.maxAlternatives = 1

    recognition.onstart = () => {
      setStatus("listening")
      callbacksRef.current.onStart?.()
    }

    recognition.onend = () => {
      setStatus("idle")
      callbacksRef.current.onStop?.()
    }

    recognition.onerror = (event) => {
      setStatus("error")
      setError(event.error)
      callbacksRef.current.onError?.(new Error(event.error))
    }

    recognition.onresult = (event) => {
      let interim = ""
      const finals: string[] = []

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i]
        const transcript = result[0]?.transcript ?? ""
        if (result.isFinal) {
          finals.push(transcript)
        } else {
          interim += transcript
        }
      }

      if (finals.length > 0) {
        setCommittedTranscripts((prev) => [
          ...prev,
          ...finals.map((text) => ({
            id: `${Date.now()}-${Math.random()}`,
            text,
            timestamp: Date.now(),
            isFinal: true,
          })),
        ])
        setPartialTranscript("")
        finals.forEach((text) =>
          callbacksRef.current.onCommittedTranscript?.({ text })
        )
      }

      setPartialTranscript(interim)
      if (interim) {
        callbacksRef.current.onPartialTranscript?.({ text: interim })
      }
    }

    recognitionRef.current = recognition
    return recognition
  }, [lang, continuous, interimResults])

  const start = useCallback(() => {
    const recognition = getRecognition()
    if (!recognition) {
      setError("Speech recognition is not supported in this browser")
      return
    }
    setError(null)
    setCommittedTranscripts([])
    setPartialTranscript("")
    setStatus("starting")
    try {
      recognition.start()
    } catch (err) {
      // Some engines throw if start() is called while already running
      if (err instanceof Error && /already|started/i.test(err.message)) {
        setStatus("listening")
        return
      }
      setStatus("error")
      setError(err instanceof Error ? err.message : "Failed to start listening")
    }
  }, [getRecognition])

  const stop = useCallback(() => {
    recognitionRef.current?.stop()
  }, [])

  const cancel = useCallback(() => {
    recognitionRef.current?.abort()
    setCommittedTranscripts([])
    setPartialTranscript("")
    setStatus("idle")
  }, [])

  const clearTranscripts = useCallback(() => {
    setCommittedTranscripts([])
    setPartialTranscript("")
  }, [])

  useEffect(() => {
    return () => {
      recognitionRef.current?.abort()
    }
  }, [])

  return {
    supported,
    status,
    isConnected: status === "listening",
    isTranscribing: status === "listening",
    isStarting: status === "starting",
    partialTranscript,
    committedTranscripts,
    error,
    start,
    stop,
    cancel,
    clearTranscripts,
  }
}

export type {
  SpeechRecognitionLike,
  SpeechRecognitionConstructor,
}
