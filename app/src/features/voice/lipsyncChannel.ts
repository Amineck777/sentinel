/**
 * チャット窓(音を鳴らす側)からアバター窓(口を動かす側)へ「いま話し始めた文」を知らせる。
 *
 * - Tauri: 窓どうしのイベント(emitTo("avatar", …))。アバター窓にコアへの接続権限は要らない
 * - ブラウザ開発: BroadcastChannel(同じオリジンのタブどうし。/ と /avatar.html の間)
 *
 * 口の形はエンジンに依存しない形(母音・開始・終了の秒)で渡す。母音が分からない
 * エンジンは visemes=null を送り、アバター側が文字から推測する(lipsync.ts)。
 */

export type VisemeTriple = [
  vowel: "aa" | "ih" | "ou" | "ee" | "oh" | null,
  start: number,
  end: number,
];

export type LipsyncMessage =
  | {
      kind: "speak";
      text: string;
      duration: number;
      visemes: VisemeTriple[] | null;
      /** この文の表情(コアの感情の名前)。分からなければ null */
      emotion?: string | null;
    }
  | { kind: "stop" };

const EVENT = "avatar://lipsync";
const CHANNEL = "sentinel-lipsync";
const isTauri = () => "__TAURI_INTERNALS__" in window;

let channel: BroadcastChannel | null = null;
const getChannel = () => (channel ??= new BroadcastChannel(CHANNEL));

export function sendLipsync(msg: LipsyncMessage): void {
  if (isTauri()) {
    void import("@tauri-apps/api/event")
      .then(({ emitTo }) => emitTo("avatar", EVENT, msg))
      .catch(() => {}); // アバター窓が無くても会話は止めない
  } else {
    getChannel().postMessage(msg);
  }
}

/** 受け取り側(アバター窓)。戻り値で購読をやめる */
export function onLipsync(cb: (msg: LipsyncMessage) => void): () => void {
  if (isTauri()) {
    let unlisten: (() => void) | undefined;
    let cancelled = false;
    void import("@tauri-apps/api/event").then(({ listen }) =>
      listen<LipsyncMessage>(EVENT, (e) => cb(e.payload)).then((u) => {
        if (cancelled) u();
        else unlisten = u;
      }),
    );
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }
  const ch = new BroadcastChannel(CHANNEL);
  ch.onmessage = (e: MessageEvent<LipsyncMessage>) => cb(e.data);
  return () => ch.close();
}
