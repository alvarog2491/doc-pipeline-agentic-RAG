import type { ReactNode } from "react";
import type { Citation } from "@doc-pipeline/shared-types";
import { renderCitations } from "../services/citations";

interface Props {
  role: "user" | "agent";
  text: string;
  citations?: Citation[];
  onManualLinkClick?: (url: string) => void;
}

// Matches **bold**, `inline code` and [label](url) link spans within a line of text.
const INLINE_MARKDOWN = /\*\*(.+?)\*\*|`(.+?)`|\[(.+?)\]\((\S+?)\)/g;

// Our citation links are presigned PDF URLs ending in "#page=N"; they open in the in-app side
// panel instead of a new browser tab.
const PDF_LINK = /(\.pdf(\?|#|$)|#page=\d+$)/i;

function renderInlineMarkdown(line: string, onManualLinkClick?: (url: string) => void): ReactNode[] {
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;

  INLINE_MARKDOWN.lastIndex = 0;
  while ((match = INLINE_MARKDOWN.exec(line)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(line.slice(lastIndex, match.index));
    }

    const [, bold, code, linkLabel, linkUrl] = match;
    if (bold !== undefined) {
      nodes.push(<strong key={key++}>{bold}</strong>);
    } else if (code !== undefined) {
      nodes.push(
        <code key={key++} className="message-code">
          {code}
        </code>,
      );
    } else if (linkLabel !== undefined && linkUrl !== undefined) {
      const openInPanel = onManualLinkClick && PDF_LINK.test(linkUrl);
      nodes.push(
        <a
          key={key++}
          href={linkUrl}
          target={openInPanel ? undefined : "_blank"}
          rel={openInPanel ? undefined : "noopener noreferrer"}
          onClick={
            openInPanel
              ? (e) => {
                  e.preventDefault();
                  onManualLinkClick(linkUrl);
                }
              : undefined
          }
        >
          {linkLabel}
        </a>,
      );
    }

    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < line.length) {
    nodes.push(line.slice(lastIndex));
  }

  return nodes;
}

const HEADING = /^(#{1,6})\s+(.*)$/;
const LIST_ITEM = /^[-*]\s+(.*)$/;

function renderParagraph(lines: string[], key: number, onManualLinkClick?: (url: string) => void): ReactNode {
  return (
    <p key={key}>
      {lines.map((line, i) => (
        <span key={i}>
          {renderInlineMarkdown(line, onManualLinkClick)}
          {i < lines.length - 1 && <br />}
        </span>
      ))}
    </p>
  );
}

function renderMarkdown(text: string, onManualLinkClick?: (url: string) => void): ReactNode {
  const lines = keepStandaloneLinksInline(text).split("\n");
  const blocks: ReactNode[] = [];
  let key = 0;
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const heading = HEADING.exec(line);
    const listItem = LIST_ITEM.exec(line);

    if (heading) {
      const level = heading[1].length;
      const HeadingTag = `h${Math.min(level, 6)}` as keyof JSX.IntrinsicElements;
      blocks.push(
        <HeadingTag key={key++}>
          {renderInlineMarkdown(heading[2], onManualLinkClick)}
        </HeadingTag>,
      );
      i++;
    } else if (listItem) {
      const items: string[] = [];
      while (i < lines.length) {
        const match = LIST_ITEM.exec(lines[i]);
        if (!match) break;
        items.push(match[1]);
        i++;
      }
      blocks.push(
        <ul key={key++}>
          {items.map((item, j) => (
            <li key={j}>{renderInlineMarkdown(item, onManualLinkClick)}</li>
          ))}
        </ul>,
      );
    } else if (line.trim() === "") {
      i++;
    } else {
      const paragraphLines: string[] = [];
      while (i < lines.length && lines[i].trim() !== "" && !HEADING.test(lines[i]) && !LIST_ITEM.test(lines[i])) {
        paragraphLines.push(lines[i]);
        i++;
      }
      blocks.push(renderParagraph(paragraphLines, key++, onManualLinkClick));
    }
  }

  return blocks;
}

// Agent citations often arrive after a newline. When the new line contains only
// a Markdown link, keep it attached to the sentence it cites instead of creating
// a separate paragraph.
function keepStandaloneLinksInline(text: string): string {
  return text.replace(
    /\n+[ \t]*(?=\[[^\]\n]+\]\(\S+\)[ \t]*(?:\n|$))/g,
    (separator, offset: number, source: string) => {
      const precedingText = source.slice(0, offset);
      const precedingLine = precedingText.slice(
        precedingText.lastIndexOf("\n") + 1,
      );

      if (HEADING.test(precedingLine) || LIST_ITEM.test(precedingLine)) {
        return separator;
      }

      return precedingLine.trim() ? " " : separator;
    },
  );
}

export function MessageBubble({ role, text, citations, onManualLinkClick }: Props) {
  return (
    <div className={`message-row message-row--${role}`}>
      <div className={`message-bubble message-bubble--${role}`}>
        {renderMarkdown(role === "agent" ? renderCitations(text, citations) : text, onManualLinkClick)}
      </div>
    </div>
  );
}
