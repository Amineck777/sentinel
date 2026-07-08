import { useState } from "react";

export function Composer({
  disabled,
  onSend,
}: {
  disabled: boolean;
  onSend: (content: string) => void;
}) {
  const [input, setInput] = useState("");

  const submit = () => {
    const content = input.trim();
    if (!content || disabled) return;
    setInput("");
    onSend(content);
  };

  return (
    <footer className="composer">
      <textarea
        value={input}
        rows={1}
        placeholder="メッセージを入力(Enterで送信 / Shift+Enterで改行)"
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
      />
      <button onClick={submit} disabled={disabled || !input.trim()}>
        送信
      </button>
    </footer>
  );
}
