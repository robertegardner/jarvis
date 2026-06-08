import { useState } from "react";

export function MessageInput({
  busy,
  onSend,
  onInterrupt,
}: {
  busy: boolean;
  onSend: (text: string) => void;
  onInterrupt: () => void;
}) {
  const [text, setText] = useState("");

  const submit = () => {
    if (!text.trim()) return;
    onSend(text);
    setText("");
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="composer">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Tell Jarvis what to do… (Enter to send, Shift+Enter for newline)"
        rows={2}
      />
      {busy ? (
        <button className="btn danger" onClick={onInterrupt} title="Stop the current turn">
          Stop
        </button>
      ) : (
        <button className="btn ok" onClick={submit} disabled={!text.trim()}>
          Send
        </button>
      )}
    </div>
  );
}
