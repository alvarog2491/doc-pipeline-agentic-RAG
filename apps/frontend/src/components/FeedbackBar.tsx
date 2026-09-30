import { useEffect, useRef, useState } from "react";
import { submitFeedback, type FeedbackOutcome } from "../services/feedback";

interface Props {
  sessionId: string;
  onRestart: () => void;
}

type Phase = "idle" | "commenting" | "submitting" | "done";

const MAX_COMMENT_LENGTH = 2000;

export function FeedbackBar({ sessionId, onRestart }: Props) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [comment, setComment] = useState("");
  const [error, setError] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (phase === "commenting") textareaRef.current?.focus();
  }, [phase]);

  const send = async (outcome: FeedbackOutcome) => {
    const fallback: Phase = outcome === "not_helpful" ? "commenting" : "idle";
    setError(false);
    setPhase("submitting");
    try {
      await submitFeedback({
        sessionId,
        outcome,
        comment: outcome === "not_helpful" ? comment : undefined,
      });
      setPhase("done");
    } catch {
      setError(true);
      setPhase(fallback);
    }
  };

  if (phase === "done") {
    return (
      <div className="feedback-bar feedback-bar--done">
        <p className="feedback-bar__prompt" role="status">
          Thank you — your feedback was recorded.
        </p>
        <button type="button" className="feedback-button" onClick={onRestart}>
          Restart the conversation
        </button>
      </div>
    );
  }

  const busy = phase === "submitting";

  return (
    <div className="feedback-bar">
      <p className="feedback-bar__prompt">Was this conversation helpful?</p>
      <div className="feedback-bar__actions">
        <button
          type="button"
          className="feedback-button"
          onClick={() => send("helpful")}
          disabled={busy}
        >
          <span aria-hidden="true">👍</span> Yes
        </button>
        <button
          type="button"
          className="feedback-button"
          onClick={() => {
            setError(false);
            setPhase("commenting");
          }}
          disabled={busy}
        >
          <span aria-hidden="true">👎</span> No
        </button>
      </div>

      {error && phase !== "commenting" && (
        <p className="feedback-bar__error" role="alert">
          Could not record your feedback. Please try again.
        </p>
      )}

      {(phase === "commenting" || (busy && comment)) && (
        <div
          className="feedback-modal__overlay"
          role="presentation"
          onClick={() => !busy && setPhase("idle")}
        >
          <form
            className="feedback-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="feedback-modal-title"
            onClick={(event) => event.stopPropagation()}
            onSubmit={(event) => {
              event.preventDefault();
              if (comment.trim() && !busy) send("not_helpful");
            }}
          >
            <h2 id="feedback-modal-title" className="feedback-modal__title">
              What went wrong?
            </h2>
            <p className="feedback-modal__hint">
              Tell us what the answers missed so we can improve the assistant.
            </p>
            <textarea
              ref={textareaRef}
              className="feedback-modal__textarea"
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              maxLength={MAX_COMMENT_LENGTH}
              rows={4}
              required
              aria-label="Describe what went wrong"
            />
            {error && (
              <p className="feedback-bar__error" role="alert">
                Could not record your feedback. Please try again.
              </p>
            )}
            <div className="feedback-modal__actions">
              <button
                type="button"
                className="feedback-button"
                onClick={() => setPhase("idle")}
                disabled={busy}
              >
                Cancel
              </button>
              <button
                type="submit"
                className="feedback-button feedback-button--primary"
                disabled={!comment.trim() || busy}
              >
                Send feedback
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
