import { useEffect, useRef, useState, type TransitionEvent } from "react";
import { completesPanelCollapse } from "./pdfSidePanelTransition";

interface Props {
  url: string;
  onClose: () => void;
}

const DEFAULT_WIDTH = 480;
const MIN_WIDTH = 320;
const MAX_WIDTH_RATIO = 0.8;

export function PdfSidePanel({ url, onClose }: Props) {
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  const [dragging, setDragging] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const draggingRef = useRef(false);

  useEffect(() => {
    let expansionFrameId = 0;
    const collapsedFrameId = requestAnimationFrame(() => {
      expansionFrameId = requestAnimationFrame(() => setExpanded(true));
    });
    return () => {
      cancelAnimationFrame(collapsedFrameId);
      cancelAnimationFrame(expansionFrameId);
    };
  }, []);

  useEffect(() => {
    function onMouseMove(e: MouseEvent) {
      if (!draggingRef.current) return;
      const maxWidth = window.innerWidth * MAX_WIDTH_RATIO;
      setWidth(Math.min(maxWidth, Math.max(MIN_WIDTH, window.innerWidth - e.clientX)));
    }
    function onMouseUp() {
      draggingRef.current = false;
      setDragging(false);
      document.body.style.userSelect = "";
    }
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, []);

  const collapse = () => {
    draggingRef.current = false;
    setDragging(false);
    document.body.style.userSelect = "";
    setExpanded(false);
  };

  const handleTransitionEnd = (event: TransitionEvent<HTMLDivElement>) => {
    if (completesPanelCollapse(expanded, event.propertyName, event.target === event.currentTarget)) {
      onClose();
    }
  };

  return (
    <div
      className={`manual-panel ${expanded ? "manual-panel--expanded" : "manual-panel--collapsed"} ${dragging ? "manual-panel--dragging" : ""}`}
      style={{ width: expanded ? width : 0 }}
      onTransitionEnd={handleTransitionEnd}
    >
      <div
        className={`manual-resizer ${dragging ? "manual-resizer--dragging" : ""}`}
        onMouseDown={() => {
          draggingRef.current = true;
          setDragging(true);
          document.body.style.userSelect = "none";
        }}
        title="Drag to resize"
      />
      <div className="manual-content">
        <div className="manual-header">
          <span>Document</span>
          <button
            className="manual-close"
            onClick={collapse}
            aria-label="Close document panel"
          >
            ✕
          </button>
        </div>
        <iframe
          // Keyed on url so a new link (even one differing only by #page=N on the same PDF)
          // remounts the iframe instead of relying on the browser to treat the src change as
          // a fresh navigation - it often doesn't, and treats a fragment-only src change as an
          // in-document scroll instead, so the embedded PDF viewer never jumps to the new page.
          key={url}
          title="Cited document"
          src={url}
          className="manual-frame"
          style={{ pointerEvents: dragging ? "none" : "auto" }}
        />
      </div>
    </div>
  );
}
