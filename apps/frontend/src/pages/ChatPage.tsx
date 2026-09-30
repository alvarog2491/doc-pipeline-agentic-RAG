import { useLayoutEffect, useRef, useState } from "react";
import type { Route } from "@doc-pipeline/shared-types";
import { useChat } from "../hooks/useChat";
import { useKnowledgeBases } from "../hooks/useKnowledgeBases";
import { MessageBubble } from "../components/MessageBubble";
import { ChatInput } from "../components/ChatInput";
import { FeedbackBar } from "../components/FeedbackBar";
import { KnowledgeBaseSelect } from "../components/KnowledgeBaseSelect";
import { UploadDocument } from "../components/UploadDocument";
import { PdfSidePanel } from "../components/PdfSidePanel";
import { TypingIndicator } from "../components/TypingIndicator";
import { ConversationScrollFollower } from "../services/conversationScroll";
import { shouldShowThinkingIndicator } from "../services/chatStreamingState";

const GREETING_MESSAGE =
  "Hi, I'm the Doc Pipeline Assistant. Pick a document above, then ask me a question, a harder multi-part question, or ask for a **step-by-step guide**.";

const ROUTE_LABEL: Record<Route, string> = {
  easy: "Quick answer",
  hard: "Deep reasoning",
  guide: "Step-by-step guide",
};

const SELECTED_KB_KEY = "docpipeline.selectedKnowledgeBase";

function readSelectedKnowledgeBase(): string | null {
  try {
    return localStorage.getItem(SELECTED_KB_KEY);
  } catch {
    return null;
  }
}

export function ChatPage() {
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID());
  const [selectedId, setSelectedId] = useState<string | null>(readSelectedKnowledgeBase);
  const { knowledgeBases, loading, error: listError, refresh, watch } = useKnowledgeBases();
  const selected = knowledgeBases.find((kb) => kb.id === selectedId && kb.status === "READY");
  const { messages, streaming, status, route, error, sendMessage, closeSession } = useChat(
    sessionId,
    selected?.id ?? null,
  );
  const hasAgentReply = messages.some((msg) => msg.role === "agent");
  const showThinkingIndicator = shouldShowThinkingIndicator(streaming);
  const conversationMainRef = useRef<HTMLElement>(null);
  const scrollFollowerRef = useRef<ConversationScrollFollower | null>(null);
  const [documentUrl, setDocumentUrl] = useState<string | null>(null);
  const [sessionClosed, setSessionClosed] = useState(false);

  const handleRestart = () => {
    setSessionClosed(false);
    setDocumentUrl(null);
    setSessionId(crypto.randomUUID());
  };

  const handleSelect = (id: string) => {
    setSelectedId(id);
    try {
      localStorage.setItem(SELECTED_KB_KEY, id);
    } catch {
      // storage unavailable: the selection simply is not remembered
    }
    handleRestart();
  };

  const handleCloseSession = () => {
    setSessionClosed(true);
    closeSession();
  };

  useLayoutEffect(() => {
    const follower = new ConversationScrollFollower(
      () => conversationMainRef.current,
      undefined,
      () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    );
    scrollFollowerRef.current = follower;

    return () => {
      follower.cancel();
      scrollFollowerRef.current = null;
    };
  }, []);

  useLayoutEffect(() => {
    scrollFollowerRef.current?.follow();
  }, [messages]);

  return (
    <div className="app-shell">
      <div className="chat-layout">
        <header className="app-header">
          <div className="brand-lockup">
            <h1>Doc Pipeline Agent</h1>
          </div>
          <KnowledgeBaseSelect
            knowledgeBases={knowledgeBases}
            selectedId={selected?.id ?? null}
            loading={loading}
            onSelect={handleSelect}
            onRefresh={refresh}
          />
          <UploadDocument onUploaded={watch} />
        </header>

        <main
          ref={conversationMainRef}
          className="conversation-main"
          onScroll={() => scrollFollowerRef.current?.handleScroll()}
        >
          <section
            className="conversation"
            aria-label="Conversation"
            aria-live="polite"
            aria-relevant="additions text"
          >
            <MessageBubble role="agent" text={GREETING_MESSAGE} />
            {knowledgeBases.length === 0 && !loading && !listError && (
              <MessageBubble
                role="agent"
                text="No documents yet. Use **Upload PDF** above; it appears in the list while it is processed and can be chatted with once it is ready."
              />
            )}
            {messages.map((msg, i) => (
              <MessageBubble
                key={`${sessionId}-${i}`}
                role={msg.role}
                text={msg.text}
                citations={msg.citations}
                onManualLinkClick={setDocumentUrl}
              />
            ))}
            {showThinkingIndicator && (
              <TypingIndicator label={status} badge={route ? ROUTE_LABEL[route] : null} />
            )}
          </section>
          {(error || listError) && (
            <p className="chat-error" role="alert">
              {error ?? listError}
            </p>
          )}
        </main>

        {sessionClosed ? (
          <FeedbackBar sessionId={sessionId} onRestart={handleRestart} />
        ) : (
          hasAgentReply &&
          !streaming && (
            <div className="session-close-bar">
              <button
                type="button"
                className="feedback-button session-close-button"
                onClick={handleCloseSession}
              >
                Close session
              </button>
            </div>
          )
        )}

        <ChatInput onSend={sendMessage} disabled={sessionClosed || streaming || !selected} />
      </div>

      {documentUrl && <PdfSidePanel url={documentUrl} onClose={() => setDocumentUrl(null)} />}
    </div>
  );
}
