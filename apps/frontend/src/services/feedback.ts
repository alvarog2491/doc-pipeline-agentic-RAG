import { apiBase } from "./chatApi";

/**
 * Whether the conversation helped the user:
 * - `helpful`     — the answers were useful
 * - `not_helpful` — they were not; a written detail is required
 */
export type FeedbackOutcome = "helpful" | "not_helpful";

export interface FeedbackSubmission {
  sessionId: string;
  outcome: FeedbackOutcome;
  comment?: string;
}

export interface FeedbackRequestBody {
  sessionId: string;
  outcome: FeedbackOutcome;
  comment?: string;
}

/** Trims the comment and drops it when empty so a bare outcome never carries a blank string. */
export function buildFeedbackBody(submission: FeedbackSubmission): FeedbackRequestBody {
  const comment = submission.comment?.trim();
  return {
    sessionId: submission.sessionId,
    outcome: submission.outcome,
    ...(comment ? { comment } : {}),
  };
}

export async function submitFeedback(
  submission: FeedbackSubmission,
  fetchImpl: typeof fetch = fetch,
): Promise<void> {
  const response = await fetchImpl(`${apiBase()}/v1/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildFeedbackBody(submission)),
  });

  if (!response.ok) {
    throw new Error(`Feedback request failed with status ${response.status}`);
  }
}
