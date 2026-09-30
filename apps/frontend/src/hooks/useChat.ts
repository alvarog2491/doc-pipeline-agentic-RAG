import { useCallback, useEffect, useRef, useState } from "react";
import type { Citation, Route, ServerEvent } from "@doc-pipeline/shared-types";
import { streamChat } from "../services/chatApi";
import { SmoothTextBuffer } from "../services/smoothTextBuffer";

export interface ChatMessage {
  role: "user" | "agent";
  text: string;
  citations?: Citation[];
}

const GENERIC_ERROR = "The assistant is unavailable. Please try again.";

/**
 * Chat state for one conversation about one document.
 *
 * A new `sessionId` starts a fresh conversation. Answer text is revealed through a small
 * smoothing buffer as `delta` events arrive, so the reply appears immediately and keeps
 * flowing instead of landing in one block.
 */
export function useChat(sessionId: string, knowledgeBaseId: string | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Latest transient status line (`progress`); cleared when the first answer text arrives.
  const [status, setStatus] = useState<string | null>(null);
  // How the orchestrator classified the current/last turn.
  const [route, setRoute] = useState<Route | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    setMessages([]);
    setStreaming(false);
    setError(null);
    setStatus(null);
    setRoute(null);
    return () => {
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, [sessionId, knowledgeBaseId]);

  const sendMessage = useCallback(
    (prompt: string) => {
      if (!knowledgeBaseId || abortRef.current) return;

      const controller = new AbortController();
      abortRef.current = controller;
      let citations: Citation[] | undefined;

      const attachCitations = () => {
        if (!citations) return;
        setMessages((previous) => {
          const last = previous[previous.length - 1];
          return last?.role === "agent"
            ? [...previous.slice(0, -1), { ...last, citations }]
            : previous;
        });
      };

      const buffer = new SmoothTextBuffer({
        onText: (text) =>
          setMessages((previous) => {
            const last = previous[previous.length - 1];
            return last?.role === "agent"
              ? [...previous.slice(0, -1), { ...last, text: last.text + text }]
              : [...previous, { role: "agent", text, citations }];
          }),
        onDrained: () => {
          attachCitations();
          abortRef.current = null;
          setStreaming(false);
        },
      });

      const onEvent = (event: ServerEvent) => {
        switch (event.type) {
          case "route":
            setRoute(event.route);
            break;
          case "progress":
            setStatus(event.text);
            break;
          case "delta":
            setStatus(null);
            buffer.enqueue(event.text);
            break;
          case "citations":
            citations = event.citations;
            attachCitations();
            break;
          case "completed":
            setStatus(null);
            buffer.complete();
            break;
          case "error":
            setStatus(null);
            setError(event.message);
            buffer.complete();
            break;
        }
      };

      setMessages((previous) => [...previous, { role: "user", text: prompt }]);
      setStreaming(true);
      setError(null);
      setStatus(null);
      setRoute(null);

      streamChat({ sessionId, knowledgeBaseId, prompt }, onEvent, controller.signal)
        .then(() => buffer.complete())
        .catch(() => {
          if (controller.signal.aborted) {
            buffer.cancel();
            return;
          }
          setStatus(null);
          setError(GENERIC_ERROR);
          buffer.complete();
        });
    },
    [sessionId, knowledgeBaseId],
  );

  /** Ends the conversation from the client; the AgentCore session expires on its own. */
  const closeSession = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setStreaming(false);
  }, []);

  return { messages, streaming, status, route, error, sendMessage, closeSession };
}
