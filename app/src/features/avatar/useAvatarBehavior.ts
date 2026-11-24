/**
 * アバター窓の「ふるまい」: チャット窓から届く合図(cueChannel・lipsyncChannel)を受けて、
 * 状態・表情・吹き出しを決め、AvatarStage に伝える(ADR 0114 / 学習ノート 07)。
 *
 * 居眠りだけはここで決める: 待機のまま一定時間なにも起きなければ眠り、
 * 合図が来るかクリックされたら慌てて(驚いた顔で)起きる。深夜は早めに眠くなる。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { onLipsync } from "../voice/lipsyncChannel";
import type { AvatarStage, Emotion } from "./avatarStage";
import { onCue, sendHello, type AvatarState, type CoreEmotion } from "./cueChannel";
import { fitText, fromTriples } from "./lipsync";

export type BubbleView =
  | { kind: "text"; text: string; speaking: boolean }
  | { kind: "thinking" }
  | { kind: "error"; text: string }
  | { kind: "sleep" }
  | null;

export type BehaviorOptions = {
  bubble: boolean;
  bubbleSeconds: number;
  emotionStrength: number;
  /** 0 なら居眠りしない */
  sleepMinutes: number;
};

/** コアの感情の名前 → VRM の表情。怒りは落ち着いたキャラに合わせてさらに弱める */
const TO_VRM: Record<CoreEmotion, { name: Emotion; scale: number }> = {
  neutral: { name: "neutral", scale: 1 },
  joy: { name: "happy", scale: 1 },
  fun: { name: "relaxed", scale: 1 },
  sorrow: { name: "sad", scale: 1 },
  angry: { name: "angry", scale: 0.7 },
  surprised: { name: "surprised", scale: 1 },
};
const isCoreEmotion = (e: unknown): e is CoreEmotion => typeof e === "string" && e in TO_VRM;

/** 話し終えて待機に戻ってから、表情をふつうに戻すまで */
const EMOTION_RESET_MS = 5000;
/** 深夜(0〜5 時)はこの分数で眠くなる(設定の分数のほうが短ければそちら) */
const NIGHT_SLEEP_MINUTES = 3;

export function useAvatarBehavior(stage: () => AvatarStage | null, options: BehaviorOptions) {
  const { bubble: bubbleOn, sleepMinutes } = options;
  const [base, setBase] = useState<Exclude<AvatarState, "sleeping">>("idle");
  const [detail, setDetail] = useState<string | undefined>();
  const [asleep, setAsleep] = useState(false);
  const [text, setText] = useState<{ text: string; speaking: boolean } | null>(null);

  const lastActivity = useRef(0);
  const textTimer = useRef<number | undefined>(undefined);
  const resetTimer = useRef<number | undefined>(undefined);
  const wakeTimer = useRef<number | undefined>(undefined);
  // 最新の設定をイベントの中から読むため(購読し直さずに済むように)
  const opts = useRef(options);
  useEffect(() => {
    opts.current = options;
  });
  const asleepRef = useRef(false);

  const applyEmotion = useCallback(
    (e: CoreEmotion) => {
      const { name, scale } = TO_VRM[e];
      stage()?.setEmotion(name, opts.current.emotionStrength * scale);
      window.clearTimeout(resetTimer.current);
    },
    [stage],
  );

  const showText = useCallback((value: string, speaking: boolean, holdMs: number) => {
    if (!opts.current.bubble) return;
    setText({ text: value, speaking });
    window.clearTimeout(textTimer.current);
    textTimer.current = window.setTimeout(() => setText(null), holdMs);
  }, []);

  /** 何か起きた。眠っていたら慌てて起きる */
  const touch = useCallback(() => {
    lastActivity.current = Date.now();
    if (!asleepRef.current) return;
    asleepRef.current = false;
    setAsleep(false);
    const st = stage();
    st?.setEmotion("surprised", 0.6);
    window.clearTimeout(wakeTimer.current);
    wakeTimer.current = window.setTimeout(() => st?.setEmotion("neutral", 1), 1200);
  }, [stage]);

  // チャット窓からの合図
  useEffect(
    () =>
      onCue((cue) => {
        touch();
        const st = stage();
        if (cue.kind === "state") {
          setBase(cue.state);
          setDetail(cue.detail);
        } else if (cue.kind === "nod") {
          st?.nod();
        } else if (cue.kind === "emotion") {
          applyEmotion(cue.emotion);
        } else if (cue.kind === "bubble") {
          const s = opts.current.bubbleSeconds;
          // 長い返事は読む時間を少し足す(1 文字 0.05 秒、最大 +10 秒)
          const hold = cue.final ? s * 1000 + Math.min(10_000, cue.text.length * 50) : 60_000;
          showText(cue.text, false, hold);
        }
      }),
    [stage, touch, applyEmotion, showText],
  );

  // 声に合わせた口パク・吹き出し・表情・文の切れ目のうなずき
  useEffect(
    () =>
      onLipsync((msg) => {
        const st = stage();
        if (!st) return;
        if (msg.kind === "stop") {
          st.stopSpeaking();
          return;
        }
        touch();
        st.speakTimeline(msg.visemes ? fromTriples(msg.visemes) : fitText(msg.text, msg.duration));
        st.nod();
        if (isCoreEmotion(msg.emotion)) applyEmotion(msg.emotion);
        showText(msg.text, true, (msg.duration + opts.current.bubbleSeconds) * 1000);
      }),
    [stage, touch, applyEmotion, showText],
  );

  // 開いたら、チャット窓に今の状態を聞く。居眠りまでの時間もここから数える
  useEffect(() => {
    lastActivity.current = Date.now();
    sendHello();
  }, []);

  // 待機に戻ったら、しばらくして表情をふつうに戻す
  useEffect(() => {
    if (base !== "idle") return;
    resetTimer.current = window.setTimeout(
      () => stage()?.setEmotion("neutral", 1),
      EMOTION_RESET_MS,
    );
    return () => window.clearTimeout(resetTimer.current);
  }, [base, stage]);

  // 居眠りの判定(10 秒ごと)
  useEffect(() => {
    if (sleepMinutes <= 0) {
      touch();
      return;
    }
    const id = window.setInterval(() => {
      if (base !== "idle") return;
      const hour = new Date().getHours();
      const minutes = hour < 5 ? Math.min(sleepMinutes, NIGHT_SLEEP_MINUTES) : sleepMinutes;
      if (Date.now() - lastActivity.current >= minutes * 60_000 && !asleepRef.current) {
        asleepRef.current = true;
        setAsleep(true);
      }
    }, 10_000);
    return () => window.clearInterval(id);
  }, [base, sleepMinutes, touch]);

  // 状態が動いたら(待機以外)起きている扱い
  useEffect(() => {
    if (base !== "idle") touch();
  }, [base, touch]);

  useEffect(
    () => () => {
      window.clearTimeout(textTimer.current);
      window.clearTimeout(resetTimer.current);
      window.clearTimeout(wakeTimer.current);
    },
    [],
  );

  const state: AvatarState = asleep && base === "idle" ? "sleeping" : base;
  useEffect(() => stage()?.setState(state), [stage, state]);

  let bubble: BubbleView = null;
  if (state === "error") bubble = { kind: "error", text: detail ?? "接続できません。" };
  else if (text) bubble = { kind: "text", ...text };
  else if (state === "thinking") bubble = { kind: "thinking" };
  else if (state === "sleeping") bubble = { kind: "sleep" };
  if (!bubbleOn && bubble?.kind !== "error") bubble = null;

  /** 試験パネル用: すぐ居眠りする */
  const sleepNow = useCallback(() => {
    asleepRef.current = true;
    setAsleep(true);
  }, []);

  return { state, bubble, touch, sleepNow } as const;
}
