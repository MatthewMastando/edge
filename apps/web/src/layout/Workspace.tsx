import { useLayoutEffect, useRef, useState } from "react";

import { ChatPanel } from "../chat/ChatPanel";
import { ThesisCanvas } from "../thesis/ThesisCanvas";
import { useWorkspace } from "../workspace/useWorkspace";

export function ResearchWorkspace() {
  const { state, dispatch } = useWorkspace();
  const [mainPx, setMainPx] = useState<number | null>(null);
  const reportRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const element = reportRef.current;
    if (!element) return;
    if (element.scrollTop !== state.scroll.report) element.scrollTop = state.scroll.report;
  }, [state.mode, state.scroll.report]);

  return (
    <div
      className="workspace"
      data-mode={state.mode}
      data-testid="workspace"
      style={mainPx === null ? undefined : { gridTemplateColumns: `${String(mainPx)}px 6px minmax(280px, 1fr)` }}
    >
      <div
        ref={reportRef}
        className="slot report"
        data-testid="report-scroll"
        data-column={state.mode === "output" ? "main" : "side"}
        data-scroll={String(state.scroll.report)}
        onScroll={(event) => {
          dispatch({ type: "scroll", slot: "report", top: event.currentTarget.scrollTop });
        }}
      >
        <ThesisCanvas />
      </div>
      <div
        className="splitter"
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize panels"
        onPointerDown={(event) => {
          const workspace = event.currentTarget.parentElement;
          if (!workspace) return;
          const rect = workspace.getBoundingClientRect();
          const move = (pointer: PointerEvent) => {
            const next = Math.min(Math.max(pointer.clientX - rect.left, 360), rect.width - 300);
            setMainPx(next);
          };
          const stop = () => {
            window.removeEventListener("pointermove", move);
            window.removeEventListener("pointerup", stop);
          };
          window.addEventListener("pointermove", move);
          window.addEventListener("pointerup", stop);
        }}
      />
      <div className="slot chat-slot" data-testid="chat-column" data-column={state.mode === "output" ? "side" : "main"}>
        <ChatPanel />
      </div>
    </div>
  );
}
