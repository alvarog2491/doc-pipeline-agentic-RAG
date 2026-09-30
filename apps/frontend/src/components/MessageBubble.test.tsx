import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MessageBubble } from "./MessageBubble";

describe("MessageBubble", () => {
  it("renders a citation link inline when it follows the answer on a new line", () => {
    const html = renderToStaticMarkup(
      <MessageBubble
        role="agent"
        text={
          "Consult the manual.\n\n[Page 4](https://example.com/manual.pdf#page=5)"
        }
      />,
    );

    expect(html).toContain(
      '<span>Consult the manual. <a href="https://example.com/manual.pdf#page=5"',
    );
    expect(html).not.toContain("<br/>");
    expect(html.match(/<p>/g)).toHaveLength(1);
  });

  it("does not fold a standalone link into a preceding list item", () => {
    const html = renderToStaticMarkup(
      <MessageBubble
        role="agent"
        text={"- First step\n[Manual](https://example.com/manual.pdf)"}
      />,
    );

    expect(html).toContain("</ul><p>");
  });
});
