"use client";

// Canned small-talk handling.
//
// These replies are static UI copy — they are never presented as a
// Response Package and never passed through the retrieval pipeline.
// Greetings are intercepted on the client before any API call, so the
// backend search path stays 100% retrieval-only (no synthesized text).

export interface CannedReply {
  text: string;
  /** Optional follow-up suggestions rendered as quick questions */
  followUps: string[];
}

type Pattern = {
  test: RegExp;
  reply: string;
  followUps: string[];
};

const PATTERNS: Pattern[] = [
  {
    test: /\b(hello|hi|hey|hiya|howdy|good\s?(morning|afternoon|evening)|greetings|yo|sup)\b/i,
    reply:
      "Hello! I can help you find information about credit scores, LTV ratios, required documents, eligibility criteria, and more from our internal knowledge base. What would you like to know?",
    followUps: [
      "Minimum credit score for VA loan?",
      "Required documents for application?",
    ],
  },
  {
    test: /\b(thanks|thank you|thx|ty|appreciated|appreciate it)\b/i,
    reply:
      "You're welcome! If you need anything else, just ask — I'll search the knowledge base for you.",
    followUps: [],
  },
  {
    test: /\b(bye|goodbye|see you|later|cya|good night)\b/i,
    reply: "Goodbye! Feel free to come back anytime you need information.",
    followUps: [],
  },
  {
    test: /\b(how are you|how's it going|how are things)\b/i,
    reply:
      "I'm running smoothly, thanks for asking! I'm here to help you find information from the knowledge base. What can I look up for you?",
    followUps: [
      "Maximum DTI ratio?",
      "First-time home buyer programs?",
    ],
  },
  {
    test: /\b(what can you do|help|how do you work|what do you do|who are you)\b/i,
    reply:
      "I search our internal knowledge base for answers to your questions about requirements, documents, and policies. Ask me about credit scores, eligibility, required documents, and more.",
    followUps: [
      "Minimum credit score for VA loan?",
      "Required documents for application?",
      "Maximum DTI ratio?",
    ],
  },
];

export function detectCannedReply(input: string): CannedReply | null {
  const trimmed = input.trim();
  if (!trimmed) return null;

  // Reject anything that looks like an actual information query.
  if (
    /\b(what|how|when|where|which|why|minimum|maximum|required|document|credit|score|rate|limit|eligib|loan|property|amount|cost|process|policy)\b/i.test(
      trimmed
    )
  ) {
    return null;
  }

  // Covers repeated tokens like "hello hello hello".
  const firstToken = trimmed.split(/\s+/)[0];
  const collapsed = firstToken && /^[!?.,]*$/.test(firstToken)
    ? trimmed
    : `${firstToken ?? ""} ${firstToken ?? ""} ${firstToken ?? ""}`;

  for (const pattern of PATTERNS) {
    if (pattern.test.test(collapsed) || pattern.test.test(trimmed)) {
      return { text: pattern.reply, followUps: pattern.followUps };
    }
  }

  // "hello hello hello..." — all-token repetitions of a greeting word.
  if (/^(\w+)(?:\s+\1){1,}$/.test(trimmed)) {
    for (const pattern of PATTERNS) {
      if (pattern.test.test(trimmed.split(/\s+/)[0])) {
        return { text: pattern.reply, followUps: pattern.followUps };
      }
    }
  }

  return null;
}
