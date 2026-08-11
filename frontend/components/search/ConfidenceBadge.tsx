"use client";

import { CheckCircle2, ShieldAlert, TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface ConfidenceBadgeProps {
  confidence: number;
  routing: "answer" | "partial" | "no_answer";
  size?: "sm" | "md" | "lg";
}

export default function ConfidenceBadge({
  confidence,
  routing,
  size = "md",
}: ConfidenceBadgeProps) {
  const sizeClasses = {
    sm: "px-2.5 py-1 text-xs",
    md: "px-3 py-1.5 text-sm",
    lg: "px-4 py-2 text-base",
  };

  const getVariant = () => {
    switch (routing) {
      case "answer":
        return "bg-success/10 text-success border-success/30";
      case "partial":
        return "bg-warning/10 text-warning border-warning/30";
      case "no_answer":
        return "bg-muted text-muted-foreground border-border";
      default:
        return "bg-accent/40 text-accent-foreground border-border";
    }
  };

  const getIcon = () => {
    switch (routing) {
      case "answer":
        return <CheckCircle2 className="w-4 h-4" />;
      case "partial":
        return <TriangleAlert className="w-4 h-4" />;
      case "no_answer":
        return <ShieldAlert className="w-4 h-4" />;
      default:
        return <CheckCircle2 className="w-4 h-4" />;
    }
  };

  const getLabel = () => {
    switch (routing) {
      case "answer":
        return "High Confidence";
      case "partial":
        return "Partial Answer";
      case "no_answer":
        return "No Answer Found";
      default:
        return "Uncertain";
    }
  };

  return (
    <Badge
      variant="outline"
      className={cn(
        "inline-flex items-center gap-1.5 font-medium whitespace-nowrap",
        sizeClasses[size],
        getVariant()
      )}
    >
      {getIcon()}
      <span>{Math.round(confidence)}%</span>
      <span className="ml-1 opacity-75">·</span>
      <span>{getLabel()}</span>
    </Badge>
  );
}
