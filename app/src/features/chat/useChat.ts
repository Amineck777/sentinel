import { useEffect, useRef, useState } from "react";
import { api, CoreInfo, openStream, StreamEvent } from "../../api/client";
import type { AvatarDirector } from "../avatar/avatarDirector";
import type { VoicePlayer } from "../voice/voicePlayer";
import { Msg } from "./types";

/**
 * 会話状態: WSイベント(token / message_done / notice)の購読と送信。
 * 他セッション由来のイベントは session_id で除外する。
 */
export function useChat(core: CoreInfo | null, player: VoicePlayer, director: AvatarDirector) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const sessionRef = useRef<string | null>(null);

  useEffect(() => {
    if (!core) return;
    return openStream(core, (e: StreamEvent) => {
      if (e.type === "token") {
        // 送信直後は session_id 未確定(POST応答前)なので null の間は受け入れる
        if (sessionRef.current && e.session_id !== sessionRef.current) return;
        director.token(e.delta);
        setMsgs((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "assistant" && last.pending) {
            return [...prev.slice(0, -1), { ...last, text: last.text + e.delta }];
          }
          return [...prev, { role: "assistant", text: e.delta, pending: true }];
        });
      } else if (e.type === "message_done") {
        if (sessionRef.current && e.session_id !== sessionRef.current) return;
        director.messageDone();
        setMsgs((prev) =>
          prev.map((m, i) => (i === prev.length - 1 ? { ...m, pending: false } : m)),
        );
      } else if (e.type === "audio_chunk") {
        if (sessionRef.current && e.session_id !== sessionRef.current) return;
        director.audioArrived();
        player.enqueue(e);
      } else if (e.type === "emotion") {
        if (sessionRef.current && e.session_id !== sessionRef.current) return;
        director.emotion(e.emotion);
      } else if (e.type === "notice") {
        // 生成の失敗(LLM に繋がらない等)では message_done が来ないので、考え中を解く
        if (e.level !== "info") director.cancelWaiting();
        // info はただのお知らせ(小さく中央に)。⚠ は注意が要るもの(warn/error)だけに付ける
        const msg: Msg =
          e.level === "info"
            ? { role: "system", text: e.text }
            : { role: "assistant", text: `⚠ ${e.text}` };
        setMsgs((prev) => [...prev, msg]);
      }
    });
  }, [core, player, director]);

  const send = async (content: string) => {
    if (!core) return;
    player.stop(); // 話している途中でも、こちらが話しかけたら黙る
    director.startTurn(true);
    setMsgs((prev) => [...prev, { role: "user", text: content }]);
    try {
      const r = await api<{ session_id: string }>(core, "/chat", {
        method: "POST",
        body: JSON.stringify({ content, session_id: sessionRef.current }),
      });
      sessionRef.current = r.session_id;
    } catch (e) {
      director.cancelWaiting();
      throw e;
    }
  };

  /** キャラから先に挨拶してもらう(起動時・キャラ切替時)。汎用モードでは何もしない */
  const greet = async () => {
    if (!core) return;
    director.startTurn(false);
    const r = await api<{ session_id: string | null }>(core, "/chat/greet", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionRef.current }),
    });
    if (r.session_id) sessionRef.current = r.session_id;
    else director.cancelWaiting(); // 汎用モードは挨拶しない
  };

  /** キャラ切替時などに新セッションを開始する(仕様 §16.3: 履歴混線防止) */
  const resetSession = () => {
    sessionRef.current = null;
  };

  return { msgs, send, greet, resetSession } as const;
}
