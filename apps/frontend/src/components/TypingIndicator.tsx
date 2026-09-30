interface TypingIndicatorProps {
  /** Optional progress line streamed by the agent; falls back to "Thinking". */
  label?: string | null;
  /** How the orchestrator routed the request, for example "Deep reasoning". */
  badge?: string | null;
}

export function TypingIndicator({ label, badge }: TypingIndicatorProps = {}) {
  const text = label?.trim() ? label : "Thinking";
  return (
    <div
      className="message-row message-row--agent"
      role="status"
      aria-label="Agent is thinking"
    >
      <div className="message-bubble message-bubble--agent message-bubble--typing">
        {badge && <span className="route-badge">{badge}</span>}
        <span className="typing-label">{text}</span>
        <span className="typing-dots" aria-hidden="true">
          <span className="typing-dot" />
          <span className="typing-dot" />
          <span className="typing-dot" />
        </span>
      </div>
    </div>
  );
}
