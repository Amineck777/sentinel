/**
 * チャット窓(会話の様子を知っている側)からアバター窓(見せる側)へ、
 * 「いまの状態」「吹き出しの文字」「表情」を知らせる(ADR 0114)。
 *
 * - Tauri: 窓どうしのイベント(emitTo)。アバター窓にコアへの接続権限は要らない
 * - ブラウザ開発: BroadcastChannel(/ と /avatar.html のタブどうし)
 *
 * アバター窓が後から開いた・読み直されたときは hello を送り、チャット窓が今の状態を送り直す。
 */

/** アバターの状態。sleeping(居眠り)はアバター窓が自分で決めるので、ここからは送らない */
export type AvatarState = "idle" | "listening" | "thinking" | "speaking" | "sleeping" | "error";

/** コアが返す感情の名前(core/sentinel_core/expression.py の EMOTIONS) */
export type CoreEmotion = "neutral" | "joy" | "fun" | "sorrow" | "angry" | "surprised";

export type AvatarCue =
  | { kind: "state"; state: Exclude<AvatarState, "sleeping">; detail?: string }
  /** 声なしで返事を見せる吹き出し。final になったら数秒後に消える */
  | { kind: "bubble"; text: string; final: boolean }
  | { kind: "emotion"; emotion: CoreEmotion }
  /** 小さくうなずく(送信した瞬間の「はい」) */
  | { kind: "nod" };

const CUE_EVENT = "avatar://cue";
const HELLO_EVENT = "avatar://hello";
const CHANNEL = "sentinel-avatar-cue";
const isTauri = () => "__TAURI_INTERNALS__" in window;

type Wire = { t: "cue"; cue: AvatarCue } | { t: "hello" };

let channel: BroadcastChannel | null = null;
const getChannel = () => (channel ??= new BroadcastChannel(CHANNEL));

function emitTo(target: string, event: string, payload?: unknown): void {
  void import("@tauri-apps/api/event")
    .then((m) => m.emitTo(target, event, payload))
    .catch(() => {}); // 相手の窓が無くても会話は止めない
}

function listenTauri<T>(event: string, cb: (payload: T) => void): () => void {
  let unlisten: (() => void) | undefined;
  let cancelled = false;
  void import("@tauri-apps/api/event").then(({ listen }) =>
    listen<T>(event, (e) => cb(e.payload)).then((u) => {
      if (cancelled) u();
      else unlisten = u;
    }),
  );
  return () => {
    cancelled = true;
    unlisten?.();
  };
}

function listenChannel(cb: (w: Wire) => void): () => void {
  const ch = new BroadcastChannel(CHANNEL);
  ch.onmessage = (e: MessageEvent<Wire>) => cb(e.data);
  return () => ch.close();
}

/** チャット窓 → アバター窓 */
export function sendCue(cue: AvatarCue): void {
  if (isTauri()) emitTo("avatar", CUE_EVENT, cue);
  else getChannel().postMessage({ t: "cue", cue } satisfies Wire);
}

export function onCue(cb: (cue: AvatarCue) => void): () => void {
  if (isTauri()) return listenTauri<AvatarCue>(CUE_EVENT, cb);
  return listenChannel((w) => w.t === "cue" && cb(w.cue));
}

/** アバター窓 → チャット窓: 「今の状態を教えて」 */
export function sendHello(): void {
  if (isTauri()) emitTo("main", HELLO_EVENT);
  else getChannel().postMessage({ t: "hello" } satisfies Wire);
}

export function onHello(cb: () => void): () => void {
  if (isTauri()) return listenTauri<null>(HELLO_EVENT, () => cb());
  return listenChannel((w) => w.t === "hello" && cb());
}
