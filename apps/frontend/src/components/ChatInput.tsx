import { useEffect, useRef, useState, type KeyboardEvent } from "react";

interface Props {
  onSend: (text: string) => void;
  disabled?: boolean;
}

interface FocusableInput {
  focus(options?: FocusOptions): void;
}

export function restoreChatInputFocus(
  input: FocusableInput | null,
  pending: boolean,
  disabled: boolean,
): boolean {
  if (!pending || disabled || !input) return pending;

  input.focus({ preventScroll: true });
  return false;
}

export function ChatInput({ onSend, disabled }: Props) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const focusReturnPendingRef = useRef(false);
  const canSend = !disabled && Boolean(value.trim());

  useEffect(() => {
    focusReturnPendingRef.current = restoreChatInputFocus(
      inputRef.current,
      focusReturnPendingRef.current,
      Boolean(disabled),
    );
  }, [disabled, value]);

  const submit = () => {
    const text = value.trim();
    if (!text || disabled) return;
    focusReturnPendingRef.current = true;
    onSend(text);
    setValue("");
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="chat-input-bar">
      <div className="chat-input-content">
        <textarea
          ref={inputRef}
          className="chat-input"
          aria-label="Message to the agent"
          rows={1}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Message the agent…"
          disabled={disabled}
        />
        <button
          className="send-button"
          onClick={submit}
          disabled={!canSend}
        >
          Send
        </button>
      </div>
    </div>
  );
}
