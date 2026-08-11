"use client"

import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { motion, useReducedMotion } from "framer-motion"
import { MicIcon, SquareIcon, XIcon } from "lucide-react"

import { cn } from "@/lib/utils"
import { useSpeechRecognition } from "@/lib/use-speech-recognition"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"

const buttonVariants = cva("!px-0", {
  variants: {
    size: {
      default: "h-9 w-9",
      sm: "h-8 w-8",
      lg: "h-10 w-10",
    },
  },
  defaultVariants: {
    size: "default",
  },
})

type ButtonSize = VariantProps<typeof buttonVariants>["size"]

export interface SpeechInputData {
  /** The current partial (in-progress) transcript */
  partialTranscript: string
  /** Array of all committed (finalized) transcripts */
  committedTranscripts: string[]
  /** Full transcript combining committed and partial transcripts */
  transcript: string
}

interface SpeechInputContextValue {
  isConnected: boolean
  isConnecting: boolean
  isSupported: boolean
  transcript: string
  partialTranscript: string
  committedTranscripts: string[]
  error: string | null
  start: () => Promise<void>
  stop: () => void
  cancel: () => void
  size: ButtonSize
}

const SpeechInputContext = React.createContext<SpeechInputContextValue | null>(
  null
)

function useSpeechInput() {
  const context = React.useContext(SpeechInputContext)
  if (!context) {
    throw new Error(
      "SpeechInput compound components must be used within a SpeechInput"
    )
  }
  return context
}

function buildTranscript({
  partialTranscript,
  committedTranscripts,
}: {
  partialTranscript: string
  committedTranscripts: string[]
}): string {
  const committed = committedTranscripts.join(" ").trim()
  const partial = partialTranscript.trim()

  if (committed && partial) {
    return `${committed} ${partial}`
  }
  return committed || partial
}

function buildData({
  partialTranscript,
  committedTranscripts,
}: {
  partialTranscript: string
  committedTranscripts: string[]
}): SpeechInputData {
  return {
    partialTranscript,
    committedTranscripts,
    transcript: buildTranscript({ partialTranscript, committedTranscripts }),
  }
}

export interface SpeechInputProps {
  children: React.ReactNode

  /**
   * Called whenever the transcript changes (partial or committed)
   */
  onChange?: (data: SpeechInputData) => void

  /**
   * Called when recording is cancelled
   */
  onCancel?: (data: SpeechInputData) => void

  /**
   * Called when recording starts
   */
  onStart?: (data: SpeechInputData) => void

  /**
   * Called when recording stops
   */
  onStop?: (data: SpeechInputData) => void

  /**
   * Additional CSS classes for the root container
   */
  className?: string

  /**
   * Size variant for the component buttons
   * @default "default"
   */
  size?: ButtonSize

  /**
   * BCP-47 language code for speech recognition
   * @default "en-US"
   */
  lang?: string

  /**
   * Keep listening continuously instead of stopping after a pause
   * @default false
   */
  continuous?: boolean

  /**
   * Emit partial (interim) transcripts while speaking
   * @default true
   */
  interimResults?: boolean

  /**
   * Called when an error occurs
   */
  onError?: (error: Error) => void
}

const SpeechInput = React.forwardRef<HTMLDivElement, SpeechInputProps>(
  function SpeechInput(
    {
      children,
      onChange,
      onCancel,
      onStart,
      onStop,
      className,
      size = "default",
      lang,
      continuous = false,
      interimResults = true,
      onError,
    },
    ref
  ) {
    const transcriptsRef = React.useRef({
      partialTranscript: "",
      committedTranscripts: [] as string[],
    })

    const recognition = useSpeechRecognition({
      lang,
      continuous,
      interimResults,
      onPartialTranscript: (data) => {
        transcriptsRef.current.partialTranscript = data.text
        onChange?.(buildData(transcriptsRef.current))
      },
      onCommittedTranscript: (data) => {
        transcriptsRef.current.committedTranscripts.push(data.text)
        transcriptsRef.current.partialTranscript = ""
        onChange?.(buildData(transcriptsRef.current))
      },
      onStart: () => {
        onStart?.(buildData(transcriptsRef.current))
      },
      onStop: () => {
        onStop?.(buildData(transcriptsRef.current))
      },
      onError,
    })

    const isConnecting = recognition.isStarting

    const start = React.useCallback(async () => {
      transcriptsRef.current = {
        partialTranscript: "",
        committedTranscripts: [],
      }
      recognition.clearTranscripts()
      recognition.start()
    }, [recognition])

    const stop = React.useCallback(() => {
      recognition.stop()
    }, [recognition])

    const cancel = React.useCallback(() => {
      const data = buildData(transcriptsRef.current)
      recognition.cancel()
      transcriptsRef.current = {
        partialTranscript: "",
        committedTranscripts: [],
      }
      onCancel?.(data)
    }, [recognition, onCancel])

    const contextValue: SpeechInputContextValue = React.useMemo(
      () => ({
        isConnected: recognition.isConnected,
        isConnecting,
        isSupported: recognition.supported,
        start,
        stop,
        cancel,
        error: recognition.error,
        size,
        ...buildData({
          partialTranscript: recognition.partialTranscript,
          committedTranscripts: recognition.committedTranscripts.map(
            (t) => t.text
          ),
        }),
      }),
      [
        recognition.isConnected,
        recognition.supported,
        recognition.error,
        recognition.partialTranscript,
        recognition.committedTranscripts,
        isConnecting,
        start,
        stop,
        cancel,
        size,
      ]
    )

    return (
      <SpeechInputContext.Provider value={contextValue}>
        <div
          ref={ref}
          className={cn(
            "relative inline-flex items-center overflow-hidden rounded-md transition-all duration-200",
            recognition.isConnected
              ? "bg-background shadow-[inset_0_0_0_1px_hsl(var(--input)),0_1px_2px_0_rgba(0,0,0,0.05)]"
              : "",
            className
          )}
        >
          {children}
        </div>
      </SpeechInputContext.Provider>
    )
  }
)

SpeechInput.displayName = "SpeechInput"

export type SpeechInputRecordButtonProps = Omit<
  React.ComponentPropsWithoutRef<typeof Button>,
  "size"
>

/**
 * Toggle button for starting/stopping speech recording.
 * Shows a microphone icon when idle and a stop icon when recording.
 */
const SpeechInputRecordButton = React.forwardRef<
  HTMLButtonElement,
  SpeechInputRecordButtonProps
>(function SpeechInputRecordButton(
  { className, onClick, variant = "ghost", disabled, ...props },
  ref
) {
  const speechInput = useSpeechInput()

  return (
    <Button
      ref={ref}
      type="button"
      variant={variant}
      onClick={(e) => {
        if (speechInput.isConnected) {
          speechInput.stop()
        } else {
          speechInput.start()
        }
        onClick?.(e)
      }}
      disabled={disabled || speechInput.isConnecting || !speechInput.isSupported}
      className={cn(
        buttonVariants({ size: speechInput.size }),
        "relative flex items-center justify-center transition-all",
        speechInput.isConnected && "scale-[80%]",
        !speechInput.isSupported && "cursor-not-allowed opacity-50",
        className
      )}
      aria-label={
        speechInput.isConnected
          ? "Stop recording"
          : speechInput.isSupported
            ? "Start recording"
            : "Voice input not supported in this browser"
      }
      title={
        speechInput.isSupported
          ? undefined
          : "Voice input isn't supported in this browser. Try Chrome or Edge."
      }
      {...props}
    >
      <Skeleton
        className={cn(
          "absolute h-4 w-4 rounded-full transition-all duration-200",
          speechInput.isConnecting
            ? "bg-primary scale-90"
            : "scale-[60%] bg-transparent"
        )}
      />
      <SquareIcon
        className={cn(
          "text-destructive absolute h-4 w-4 fill-current transition-all duration-200",
          !speechInput.isConnecting && speechInput.isConnected
            ? "scale-100 opacity-100"
            : "scale-[60%] opacity-0"
        )}
      />
      <MicIcon
        className={cn(
          "absolute h-4 w-4 transition-all duration-200",
          !speechInput.isConnecting && !speechInput.isConnected
            ? "scale-100 opacity-100"
            : "scale-[60%] opacity-0"
        )}
      />
    </Button>
  )
})

SpeechInputRecordButton.displayName = "SpeechInputRecordButton"

export interface SpeechInputPreviewProps
  extends React.ComponentPropsWithoutRef<"div"> {
  /**
   * Text to show when no transcript is available
   * @default "Listening..."
   */
  placeholder?: string
}

/**
 * Displays the current transcript with a placeholder when empty.
 * Only visible when actively recording.
 */
const SpeechInputPreview = React.forwardRef<
  HTMLDivElement,
  SpeechInputPreviewProps
>(function SpeechInputPreview(
  { className, placeholder = "Listening...", ...props },
  ref
) {
  const speechInput = useSpeechInput()
  const reduceMotion = useReducedMotion()

  const displayText = speechInput.transcript || placeholder
  const showPlaceholder = !speechInput.transcript.trim()

  return (
    <div
      ref={ref}
      inert={speechInput.isConnected ? undefined : true}
      className={cn(
        "relative self-stretch text-sm transition-[opacity,transform,width] duration-200 ease-out",
        showPlaceholder
          ? "text-muted-foreground italic"
          : "text-muted-foreground",
        speechInput.isConnected ? "w-28 opacity-100" : "w-0 opacity-0",
        className
      )}
      title={displayText}
      aria-hidden={!speechInput.isConnected}
      {...props}
    >
      <div className="absolute inset-y-0 -right-1 -left-1 [mask-image:linear-gradient(to_right,transparent,black_10px,black_calc(100%-10px),transparent)]">
        <motion.p
          key="text"
          layout={reduceMotion ? false : "position"}
          className="absolute top-0 right-0 bottom-0 flex h-full min-w-full items-center px-1 whitespace-nowrap"
        >
          {displayText}
        </motion.p>
      </div>
    </div>
  )
})

SpeechInputPreview.displayName = "SpeechInputPreview"

export type SpeechInputCancelButtonProps = Omit<
  React.ComponentPropsWithoutRef<typeof Button>,
  "size"
>

/**
 * Button to cancel the current recording and discard the transcript.
 * Only visible when actively recording.
 */
const SpeechInputCancelButton = React.forwardRef<
  HTMLButtonElement,
  SpeechInputCancelButtonProps
>(function SpeechInputCancelButton(
  { className, onClick, variant = "ghost", ...props },
  ref
) {
  const speechInput = useSpeechInput()

  return (
    <Button
      ref={ref}
      type="button"
      variant={variant}
      inert={speechInput.isConnected ? undefined : true}
      onClick={(e) => {
        speechInput.cancel()
        onClick?.(e)
      }}
      className={cn(
        buttonVariants({ size: speechInput.size }),
        "transition-[opacity,transform,width] duration-200 ease-out",
        speechInput.isConnected
          ? "scale-[80%] opacity-100"
          : "pointer-events-none w-0 scale-100 opacity-0",
        className
      )}
      aria-label="Cancel recording"
      {...props}
    >
      <XIcon className="h-3 w-3" />
    </Button>
  )
})

SpeechInputCancelButton.displayName = "SpeechInputCancelButton"

export {
  SpeechInput,
  SpeechInputRecordButton,
  SpeechInputPreview,
  SpeechInputCancelButton,
  useSpeechInput,
}
