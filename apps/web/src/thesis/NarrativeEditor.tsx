import Placeholder from "@tiptap/extension-placeholder";
import { Markdown } from "@tiptap/markdown";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { useEffect, useRef } from "react";

export function NarrativeEditor({
  markdown,
  revisionKey,
  readOnly,
  onChange,
}: {
  markdown: string;
  revisionKey: string;
  readOnly: boolean;
  onChange: (markdown: string) => void;
}) {
  const onChangeRef = useRef(onChange);
  const ready = useRef(false);

  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  const editor = useEditor({
    extensions: [
      StarterKit,
      Markdown,
      Placeholder.configure({ placeholder: "Narrative. Keep numbers in the structured block." }),
    ],
    content: markdown,
    contentType: "markdown",
    immediatelyRender: true,
    editable: !readOnly,
    editorProps: {
      attributes: {
        "aria-label": "Thesis narrative",
        "aria-multiline": "true",
        role: "textbox",
        "data-testid": "narrative-editor",
      },
    },
    onUpdate: ({ editor: instance }) => {
      if (!ready.current) return;
      onChangeRef.current(instance.getMarkdown());
    },
  });

  useEffect(() => {
    ready.current = true;
  }, [editor]);

  useEffect(() => {
    editor.setEditable(!readOnly);
  }, [editor, readOnly]);

  const loaded = useRef(revisionKey);
  useEffect(() => {
    if (loaded.current === revisionKey) return;
    loaded.current = revisionKey;
    editor.commands.setContent(markdown, { contentType: "markdown", emitUpdate: false });
  }, [editor, markdown, revisionKey]);

  return (
    <section className="narrative" aria-label="Narrative">
      <h3>Narrative</h3>
      <EditorContent editor={editor} className="prose" />
    </section>
  );
}
