import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { TypingIndicator } from "./TypingIndicator";

describe("TypingIndicator", () => {
  it("shows a visible thinking label while the agent is processing", () => {
    const html = renderToStaticMarkup(<TypingIndicator />);

    expect(html).toContain("Thinking");
    expect(html).toContain('role="status"');
    expect(html).toContain('aria-label="Agent is thinking"');
  });

  it("shows the streamed progress line when one is provided", () => {
    const html = renderToStaticMarkup(
      <TypingIndicator label="Consulting the manual's safety rules…" />,
    );

    expect(html).toContain("Consulting the manual&#x27;s safety rules");
    expect(html).not.toContain(">Thinking<");
  });
});
