import { useLayoutEffect, useRef, useState } from "react";

import { provenanceLabel } from "../lib/provenance";
import { shouldUseMocks } from "../mocks/mode";
import { loadArtifactBundle, streamFixtureResearch } from "../research/fixture";
import { useWorkspace } from "../workspace/useWorkspace";

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
}

export function ChatPanel() {
  const { state, dispatch } = useWorkspace();
  const conversation = state.conversations.find((item) => item.id === state.activeConversationId) ?? null;
  const scroller = useRef<HTMLDivElement>(null);
  const seen = useRef({ id: conversation?.id ?? "", count: conversation?.messages.length ?? 0 });
  const [text, setText] = useState("");
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const live = !shouldUseMocks();
  const top = state.scroll.chat;
  const messageCount = conversation?.messages.length ?? 0;

  useLayoutEffect(() => {
    const element = scroller.current;
    if (!conversation || !element) return;
    const sameConversation = seen.current.id === conversation.id;
    const appended = sameConversation && messageCount > seen.current.count;
    seen.current = { id: conversation.id, count: messageCount };
    if (appended) {
      element.scrollTop = element.scrollHeight;
      if (element.scrollTop !== top) {
        dispatch({ type: "scroll", slot: "chat", top: element.scrollTop });
      }
      return;
    }
    if (element.scrollTop !== top) element.scrollTop = top;
  }, [conversation, dispatch, messageCount, state.mode, top]);

  const startResearch = (message: string) => {
    const question = message.trim();
    if (!question || running || !conversation) return;
    const originId = conversation.id;
    setRunning(true);
    setRunError(null);
    dispatch({
      type: "appendChat",
      conversationId: originId,
      message: {
        id: crypto.randomUUID(),
        role: "user",
        content: question,
        createdAt: new Date().toISOString(),
        provenance: null,
      },
    });
    let bound = originId;
    void streamFixtureResearch(
      {
        message: question,
        conversationId: isUuid(originId) ? originId : null,
        clientMessageId: `web-${crypto.randomUUID()}`,
      },
      (event) => {
        if (event.conversation_id && bound !== event.conversation_id) {
          dispatch({ type: "renameConversation", from: bound, to: event.conversation_id, title: "6EZ6 research" });
          bound = event.conversation_id;
        }
        const demonstration = event.is_demonstration === true || event.event === "done" || event.event === "message";
        dispatch({
          type: "appendChat",
          conversationId: bound,
          message: {
            id: crypto.randomUUID(),
            role: "assistant",
            content: event.stage ? `${event.stage}: ${event.message}` : event.message,
            createdAt: new Date().toISOString(),
            provenance: demonstration ? "recorded" : null,
          },
        });
        if (event.event === "done" && event.artifact_id) {
          void loadArtifactBundle(event.artifact_id).then((bundle) => {
            if (!bundle) return;
            dispatch({
              type: "openSavedArtifact",
              artifact: bundle.artifact,
              revisions: bundle.revisions,
              draft: bundle.draft,
              run: bundle.run,
              conversationId: bundle.artifact.conversationId ?? bound,
            });
          });
        }
        if (event.event === "error") setRunError(event.message);
      },
    )
      .catch((error: unknown) => {
        setRunError(error instanceof Error ? error.message : "Research failed");
      })
      .finally(() => {
        setRunning(false);
      });
  };

  if (!conversation) return <p className="hint">No conversation.</p>;

  return (
    <section className="chat" aria-label="Conversation">
      <header className="chat-head">
        <div>
          <h2>{conversation.title}</h2>
          {conversation.attachment ? (
            <p className="hint">
              Context: {conversation.attachment.kind} · {conversation.attachment.label}
            </p>
          ) : (
            <p className="hint">No attachment. You can start a new chat with an instrument, watchlist, or artifact.</p>
          )}
        </div>
        {live ? (
          <button
            type="button"
            className="primary"
            data-testid="run-6ez6"
            disabled={running}
            onClick={() => {
              startResearch("Research 6EZ6 on the fixture path.");
            }}
          >
            {running ? "Research running" : "Research 6EZ6"}
          </button>
        ) : null}
      </header>
      <div
        ref={scroller}
        className="messages"
        data-testid="chat-scroll"
        data-scroll={String(top)}
        onScroll={(event) => {
          dispatch({ type: "scroll", slot: "chat", top: event.currentTarget.scrollTop });
        }}
      >
        {conversation.messages.length === 0 ? (
          <p className="hint">
            {live
              ? "Run fixture research for 6EZ6. Progress streams here. Nothing on this page can place an order."
              : "New conversation. Replies in this shell are recorded demonstrations until the harness is connected."}
          </p>
        ) : null}
        {runError ? <p role="alert">{runError}</p> : null}
        <ol>
          {conversation.messages.map((message) => {
            const label = message.provenance ? provenanceLabel(message.provenance) : null;
            return (
              <li key={message.id} className={`message message-${message.role}`}>
                <span className="who">{message.role === "user" ? "You" : "Research"}</span>
                {label?.isDemonstration ? <span className="banner banner-inline">{label.text}</span> : null}
                <p>{message.content}</p>
              </li>
            );
          })}
        </ol>
      </div>
      <form
        className="composer"
        onSubmit={(event) => {
          event.preventDefault();
          if (live) startResearch(text);
          else dispatch({ type: "sendMessage", text });
          setText("");
        }}
      >
        <label className="sr-only" htmlFor="chat-input">
          Message
        </label>
        <textarea
          id="chat-input"
          value={text}
          rows={2}
          placeholder="Ask about the open research. Nothing here can place an order."
          onChange={(event) => {
            setText(event.target.value);
          }}
        />
        <button type="submit" className="primary" disabled={live && running}>
          Send
        </button>
      </form>
    </section>
  );
}
