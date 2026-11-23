import { useEffect, useRef } from "react";
import { Msg } from "./types";

export function MessageLog({ msgs }: { msgs: Msg[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs]);

  return (
    <main className="log">
      {msgs.length === 0 && (
        <p className="empty">
          メッセージを送るとここに会話が表示されます。LLMがOFFLINEのときはオフライン応答が返ります。
        </p>
      )}
      {msgs.map((m, i) =>
        m.role === "system" ? (
          <p key={i} className="sysnote">
            {m.text}
          </p>
        ) : (
          <div key={i} className={`msg msg--${m.role}`}>
            <div className="bubble">{m.text}</div>
          </div>
        ),
      )}
      <div ref={bottomRef} />
    </main>
  );
}
