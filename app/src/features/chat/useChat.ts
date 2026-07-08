import { useEffect, useRef, useState } from "react";
import { api, CoreInfo, openStream, StreamEvent } from "../../api/client";
import { Msg } from "./types";

/**
 * 会話状態: WSイベント(token / message_done / notice)の購読と送信。
 * 他セッション由来のイベントは session_id で除外する。
 */
export function useChat(core: CoreInfo | null) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const sessionRef = useRef<string | null>(null);

  useEffect(() => {
    if (!core) return;
    return openStream(core, (e: StreamEvent) => {
      if (e.type === "token") {
        // 送信直後は session_id 未確定(POST応答前)なので null の間は受け入れる
        if (sessionRef.current && e.session_id !== sessionRef.current) return;
        setMsgs((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "assistant" && last.pending) {
            return [...prev.slice(0, -1), { ...last, text: last.text + e.delta }];
          }
          return [...prev, { role: "assistant", text: e.delta, pending: true }];
        });
      } else if (e.type === "message_done") {
        if (sessionRef.current && e.session_id !== sessionRef.current) return;
        setMsgs((prev) =>
          prev.map((m, i) => (i === prev.length - 1 ? { ...m, pending: false } : m)),
        );
      } else if (e.type === "notice") {
        setMsgs((prev) => [...prev, { role: "assistant", text: `⚠ ${e.text}` }]);
      }
    });
  }, [core]);

  const send = async (content: string) => {
    if (!core) return;
    setMsgs((prev) => [...prev, { role: "user", text: content }]);
    const r = await api<{ session_id: string }>(core, "/chat", {
      method: "POST",
      body: JSON.stringify({ content, session_id: sessionRef.current }),
    });
    sessionRef.current = r.session_id;
  };

  /** キャラ切替時などに新セッションを開始する(仕様 §16.3: 履歴混線防止) */
  const resetSession = () => {
    sessionRef.current = null;
  };

  return { msgs, send, resetSession } as const;
}
