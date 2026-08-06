"use client"

import { cn } from "@/lib/utils"

interface ResponseProps {
  children: React.ReactNode
  className?: string
}

export function Response({ children, className }: ResponseProps) {
  return (
    <div
      className={cn(
        "text-sm leading-relaxed whitespace-pre-wrap break-words",
        className
      )}
    >
      {children}
    </div>
  )
}