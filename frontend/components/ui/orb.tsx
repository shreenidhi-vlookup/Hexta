"use client"

import { motion } from "framer-motion"

export type AgentState = "talking" | "listening" | null

interface OrbProps {
  agentState: AgentState
  className?: string
}

export function Orb({ agentState, className }: OrbProps) {
  const isActive = agentState === "talking" || agentState === "listening"

  return (
    <motion.div
      className={className}
      animate={
        isActive
          ? {
              scale: [1, 1.15, 1],
              opacity: [0.7, 1, 0.7],
            }
          : { scale: 1, opacity: 0.5 }
      }
      transition={
        isActive
          ? {
              repeat: Infinity,
              duration: 1.2,
              ease: "easeInOut",
            }
          : { duration: 0.3 }
      }
    >
      <div
        className={`rounded-full ${
          isActive ? "bg-primary" : "bg-muted-foreground"
        }`}
      />
    </motion.div>
  )
}