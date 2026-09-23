import { useLayoutEffect, useRef, useState } from "react";

import { provenanceLabel } from "../lib/provenance";
import { useWorkspace } from "../workspace/useWorkspace";

export function ChatPanel() {
  const { state, dispatch } = useWorkspace();
  const conversation = state.conversations.find((item) => item.id === state.activeConversationId) ?? null;
  const scroller = useRef<HTMLDivElement>(null);
  const [text, setText] = useState("");
  const top = state.scroll.chat;

  useLayoutEffect(() => {
    const element = scroller.current;
    if (!element) return;
    if (element.scrollTop !== top) element.scrollTop = top;
  }, [state.mode, top]);

  if (!conversation) return <p className="hint">No conversation.</p>;

  return (
    <section className="chat" aria-label="Conversation">
      <header className="chat-head">
        <h2>{conversation.title}</h2>
        {conversation.attachment ? (
          <p className="hint">
            Context: {conversation.attachment.kind} · {conversation.attachment.label}
          </p>
        ) : (
          <p className="hint">No attachment. You can start a new chat with an instrument, watchlist, or artifact.</p>
        )}
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
            New conversation. Replies in this shell are recorded demonstrations until the harness is connected.
          </p>
        ) : null}
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
          dispatch({ type: "sendMessage", text });
          setText("");
        }}
      >
        <label className="sr-only" htmlFor="chat-input">
          Message
        </label>
        <textarea
          id="chat-input"
          value={text}
          rows={3}
          placeholder="Ask about the open research. Nothing here can place an order."
          onChange={(event) => {
            setText(event.target.value);
          }}
        />
        <button type="submit" className="primary">
          Send
        </button>
      </form>
    </section>
  );
}
