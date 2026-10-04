// Outcome classes, ordered best → worst. Colors come from the fixed status
// palette (never reused for series); every use pairs the color with a label.

export type OutcomeMeta = {
  label: string;
  tone: "good" | "warning" | "serious" | "critical" | "neutral";
  hint: string;
  action: string;
};

export const OUTCOMES: Record<string, OutcomeMeta> = {
  success: {
    label: "Success",
    tone: "good",
    hint: "Responded and every expectation held.",
    action: "Nothing to do.",
  },
  failed_assert: {
    label: "Failed check",
    tone: "warning",
    hint: "Responded, but an expectation failed.",
    action: "Compare the final text with the case's expectations.",
  },
  agent_error: {
    label: "Agent error",
    tone: "serious",
    hint: "Non-2xx status or a failed terminal state.",
    action: "Open the trajectory to see the status code and response body.",
  },
  timeout: {
    label: "Timeout",
    tone: "critical",
    hint: "Exceeded the request or poll time budget.",
    action: "Raise timeout_s, or check whether the agent is overloaded.",
  },
  transport_error: {
    label: "Unreachable",
    tone: "critical",
    hint: "DNS, connection refused or TLS failure.",
    action: "Check the URL is reachable from the controller (inside Docker, localhost is the container).",
  },
  config_error: {
    label: "Config error",
    tone: "neutral",
    hint: "The request could not be built.",
    action: "Fix the contract: a template variable or ${SECRET} is missing.",
  },
};

export const OUTCOME_ORDER = Object.keys(OUTCOMES);

export function outcomeMeta(cls: string): OutcomeMeta {
  return OUTCOMES[cls] ?? { label: cls, tone: "neutral", hint: "", action: "" };
}

export function sortOutcomes<T>(entries: [string, T][]): [string, T][] {
  const rank = (k: string) => {
    const i = OUTCOME_ORDER.indexOf(k);
    return i === -1 ? 99 : i;
  };
  return [...entries].sort((a, b) => rank(a[0]) - rank(b[0]));
}

/** Categorical series slots (fixed order, never cycled) for agent identity. */
export const SERIES_SLOTS = 8;
export function seriesVar(index: number): string {
  return `var(--series-${(index % SERIES_SLOTS) + 1})`;
}
