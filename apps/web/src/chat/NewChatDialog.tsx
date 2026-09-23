import { useState } from "react";
import { useNavigate } from "@tanstack/react-router";

import { useInstruments } from "../api/queries";
import { Modal } from "../components/Modal";
import { useWorkspace } from "../workspace/useWorkspace";
import type { Attachment } from "../workspace/types";

export function NewChatDialog() {
  const { state, dispatch } = useWorkspace();
  const navigate = useNavigate();
  const instruments = useInstruments();
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<Attachment["kind"] | "none">("none");
  const [target, setTarget] = useState("");

  if (!state.newChatOpen) return null;

  const close = () => {
    dispatch({ type: "closeNewChat" });
  };

  const options =
    kind === "instrument"
      ? (instruments.data ?? []).map((instrument) => ({ id: instrument.id, label: `${instrument.symbol} · ${instrument.name}` }))
      : kind === "watchlist"
        ? state.watchlists.map((watchlist) => ({ id: watchlist.id, label: watchlist.name }))
        : kind === "artifact"
          ? state.artifacts.map((artifact) => ({ id: artifact.id, label: artifact.title }))
          : [];

  return (
    <Modal title="New chat" onClose={close}>
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          const selected = options.find((option) => option.id === target);
          const attachment: Attachment | null =
            kind === "none" || !selected ? null : { kind, id: selected.id, label: selected.label };
          dispatch({ type: "startConversation", title, attachment });
          void navigate({ to: "/" });
          setTitle("");
          setKind("none");
          setTarget("");
        }}
      >
        <label className="field">
          <span>Title</span>
          <input
            aria-label="Conversation title"
            value={title}
            placeholder="Optional"
            onChange={(event) => {
              setTitle(event.target.value);
            }}
          />
        </label>
        <fieldset>
          <legend>Attach context</legend>
          {(
            [
              ["none", "Nothing"],
              ["instrument", "Instrument"],
              ["watchlist", "Watchlist"],
              ["artifact", "Artifact"],
            ] as const
          ).map(([value, label]) => (
            <label key={value} className="choice">
              <input
                type="radio"
                name="attachment"
                checked={kind === value}
                onChange={() => {
                  setKind(value);
                  setTarget("");
                }}
              />
              {label}
            </label>
          ))}
        </fieldset>
        {kind !== "none" ? (
          <label className="field">
            <span>Choose</span>
            <select
              aria-label="Attachment"
              value={target}
              onChange={(event) => {
                setTarget(event.target.value);
              }}
            >
              <option value="">Select</option>
              {options.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {instruments.isError ? <p role="alert">Instrument list is unavailable. Watchlists and artifacts still work.</p> : null}
        <button type="submit" className="primary">
          Start conversation
        </button>
      </form>
    </Modal>
  );
}
