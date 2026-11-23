import { useState } from "react";

export function Composer({
  disabled,
  onSend,
  onTypingChange,
}: {
  disabled: boolean;
  onSend: (content: string) => void;
  /** 入力欄に文字があるか(アバターが「聞いている」姿勢になる) */
  onTypingChange?: (typing: boolean) => void;
}) {
  const [input, setInput] = useState("");
  const change = (value: string) => {
    setInput(value);
    onTypingChange?.(value.trim().length > 0);
  };

  const submit = () => {
    const content = input.trim();
    if (!content || disabled) return;
    change("");
    onSend(content);
  };

  return (
    <footer className="composer">
      <textarea
        value={input}
        rows={1}
        placeholder="メッセージを入力(Enterで送信 / Shift+Enterで改行)"
        onChange={(e) => change(e.target.value)}
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
