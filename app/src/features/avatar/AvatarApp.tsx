// アバター試作ページ(ロードマップ v1.2 段階A: 表示・表情・口パク)。
// http://localhost:5173/avatar.html で開く。モデルはリポジトリに入れず、
// app/.env.local の SENTINEL_AVATAR_VRM(開発サーバーが /__avatar/model.vrm で返す)か、ドラッグ&ドロップで読む。
//
// Tauri の avatar 窓(透明・枠なし・最前面)に載ったときは「デスクトップ表示」になる:
// 背景を透明にし、操作パネルを隠し、ドラッグで窓ごと動かす。ダブルクリックでパネルを出し入れする。
// 体以外の透明な部分はクリックが下のアプリへ通る(useClickThrough)。状態・吹き出し・表情は
// チャット窓からの合図で動く(useAvatarBehavior, ADR 0114)。
import { useCallback, useEffect, useRef, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import {
  DEFAULT_SHELL_SETTINGS,
  getSettings,
  onSettingsChanged,
  readAvatarModel,
  type ShellSettings,
} from "../settings/shellSettings";
import { AvatarStage, EMOTIONS, type Emotion, type ModelInfo } from "./avatarStage";
import { Bubble } from "./Bubble";
import { sendCue, type AvatarState } from "./cueChannel";
import { useAvatarBehavior } from "./useAvatarBehavior";
import { HIT_CLASS, useClickThrough } from "./useClickThrough";

const fileName = (path: string) => path.split(/[\\/]/).pop() ?? path;

const LOCAL_MODEL_URL = "/__avatar/model.vrm";
/** Tauri の窓の中で動いているか(ブラウザには __TAURI_INTERNALS__ が無い) */
const IN_TAURI = "__TAURI_INTERNALS__" in window;
// VRM 1.0 の標準表情(プリセット)。モデルによってはこれ以外に ARKit 由来の表情を大量に持つ
const PRESETS = new Set([
  ...["happy", "angry", "sad", "relaxed", "surprised", "neutral"],
  ...["aa", "ih", "ou", "ee", "oh", "blink", "blinkLeft", "blinkRight"],
  ...["lookUp", "lookDown", "lookLeft", "lookRight"],
]);
const EMOTION_LABEL: Record<Emotion, string> = {
  neutral: "ふつう",
  happy: "うれしい",
  angry: "おこる",
  sad: "かなしい",
  relaxed: "やすらぎ",
  surprised: "おどろき",
};
const STATE_LABEL: Record<Exclude<AvatarState, "sleeping">, string> = {
  idle: "待機",
  listening: "聞いている",
  thinking: "考え中",
  speaking: "話し中",
  error: "困り",
};

type Status =
  | { kind: "idle" }
  | { kind: "loading"; source: string }
  | { kind: "ready"; info: ModelInfo; source: string }
  | { kind: "error"; message: string };

export function AvatarApp() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stageRef = useRef<AvatarStage | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [emotion, setEmotion] = useState<Emotion>("neutral");
  const [weight, setWeight] = useState(1);
  const [text, setText] = useState("こんにちは、センチネルです。今日もよろしくね!");
  const [moraSec, setMoraSec] = useState(0.13);
  const [blink, setBlink] = useState(true);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(!IN_TAURI);
  const [shell, setShell] = useState<ShellSettings>(DEFAULT_SHELL_SETTINGS);

  const getStage = useCallback(() => stageRef.current, []);
  const getCanvas = useCallback(() => canvasRef.current, []);
  const behavior = useAvatarBehavior(getStage, {
    bubble: shell.avatarBubble,
    bubbleSeconds: shell.avatarBubbleSeconds,
    emotionStrength: shell.avatarEmotionStrength,
    sleepMinutes: shell.avatarSleepMinutes,
  });
  useClickThrough(getStage, getCanvas, {
    active: IN_TAURI,
    // モデルが無いとき・試験パネルを開いているときは、窓全体でクリックを受ける
    enabled: shell.avatarClickThrough && status.kind === "ready" && !panelOpen,
  });
  useEffect(() => {
    if (stageRef.current) stageRef.current.followCursor = shell.avatarFollowCursor;
  }, [shell.avatarFollowCursor]);

  const load = useCallback(async (url: string, source: string) => {
    const stage = stageRef.current;
    if (!stage) return;
    setStatus({ kind: "loading", source });
    try {
      const info = await stage.load(url);
      setStatus({ kind: "ready", info, source });
    } catch (e) {
      setStatus({ kind: "error", message: e instanceof Error ? e.message : String(e) });
    }
  }, []);

  useEffect(() => {
    // デスクトップ表示ではドラッグを「窓の移動」に使うので、カメラの回転は切る
    const stage = new AvatarStage(canvasRef.current!, { orbit: !IN_TAURI });
    stageRef.current = stage;
    if (import.meta.env.DEV) {
      (window as Window & { __avatarStage?: AvatarStage }).__avatarStage = stage;
    }
    let cancelled = false;
    let unlisten: (() => void) | undefined;

    // 開発サーバーにローカルモデル(.env.local)が設定されていれば読む
    const loadDevModel = () =>
      fetch(LOCAL_MODEL_URL, { method: "HEAD" })
        .then((r) => {
          if (r.ok && !cancelled) void load(LOCAL_MODEL_URL, "SENTINEL_AVATAR_VRM");
        })
        .catch(() => {});

    // 設定画面で選んだモデルを読む。配布版でも動くよう、ファイルは Rust に読んでもらう
    const loadConfiguredModel = async (path: string) => {
      const bytes = await readAvatarModel();
      if (cancelled) return;
      const url = URL.createObjectURL(new Blob([bytes]));
      await load(url, fileName(path));
      URL.revokeObjectURL(url);
    };

    if (IN_TAURI) {
      // 設定のモデルが変わったときだけ読み直す(表示・最前面の変更では読み直さない)
      let current: string | null | undefined;
      const sync = (path: string | null) => {
        if (path === current) return;
        current = path;
        if (path) {
          loadConfiguredModel(path).catch((e: unknown) =>
            setStatus({ kind: "error", message: String(e) }),
          );
        } else {
          void loadDevModel();
        }
      };
      getSettings()
        .then((s) => {
          setShell(s);
          sync(s.avatarModelPath);
        })
        .catch(() => void loadDevModel());
      void onSettingsChanged((s) => {
        setShell(s);
        sync(s.avatarModelPath);
      }).then((u) => {
        if (cancelled) u();
        else unlisten = u;
      });
    } else {
      void loadDevModel();
    }

    return () => {
      cancelled = true;
      unlisten?.();
      stage.dispose();
      stageRef.current = null;
    };
  }, [load]);

  useEffect(() => {
    // 背景の透明化は html/body に掛けないと効かないので、ルート要素に印を付ける
    document.documentElement.classList.toggle("avatar-desktop", IN_TAURI);
  }, []);

  useEffect(() => stageRef.current?.setEmotion(emotion, weight), [emotion, weight]);
  useEffect(() => {
    if (stageRef.current) stageRef.current.blinkEnabled = blink;
  }, [blink]);

  // 枠なし窓にはタイトルバーが無いので、キャンバスを掴んだら窓ごと動かす
  const onCanvasMouseDown = (e: React.MouseEvent) => {
    behavior.touch(); // 触ったら起きる
    if (IN_TAURI && e.button === 0 && e.detail === 1) void getCurrentWindow().startDragging();
  };

  const openChat = () => {
    if (!IN_TAURI) return;
    void import("@tauri-apps/api/core").then(({ invoke }) => invoke("show_chat"));
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) void load(URL.createObjectURL(file), file.name);
  };

  const onPickModel = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) void load(URL.createObjectURL(file), file.name);
  };

  const onPickAudio = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) setAudioUrl(URL.createObjectURL(file));
  };

  // 音声を再生しながら、その音量で口を動かす
  const onAudioPlay = () => {
    const el = audioRef.current;
    const stage = stageRef.current;
    if (!el || !stage) return;
    if (!audioCtxRef.current) {
      // AudioContext はユーザー操作の後でないと音が出ない(自動再生の制限)ので、ここで作る
      const ctx = new AudioContext();
      const src = ctx.createMediaElementSource(el);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      src.connect(analyser);
      analyser.connect(ctx.destination);
      audioCtxRef.current = ctx;
      analyserRef.current = analyser;
    }
    void audioCtxRef.current.resume();
    stage.attachAudio(analyserRef.current);
  };

  return (
    <div
      className={`avatar-page${panelOpen ? "" : " panel-closed"}`}
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDrop}
    >
      <canvas
        ref={canvasRef}
        className="avatar-canvas"
        onMouseDown={onCanvasMouseDown}
        onDoubleClick={() => IN_TAURI && setPanelOpen((v) => !v)}
      />
      {status.kind === "ready" && (
        <Bubble view={behavior.bubble} onOpenChat={IN_TAURI ? openChat : undefined} />
      )}
      {status.kind !== "ready" && (
        <div className="avatar-overlay">
          {status.kind === "loading" && <p>読み込み中… {status.source}</p>}
          {status.kind === "error" && (
            <p className="avatar-error">読み込み失敗: {status.message}</p>
          )}
          {status.kind === "idle" && (
            <p>
              .vrm ファイルをここへドロップ
              <br />
              <small>
                {IN_TAURI
                  ? "(メイン窓の右上の歯車 → 設定でモデルを選ぶと、次から自動で読みます)"
                  : "(app/.env.local に SENTINEL_AVATAR_VRM を書くと自動で読みます)"}
              </small>
            </p>
          )}
        </div>
      )}

      {panelOpen && (
        <aside className={`avatar-panel ${HIT_CLASS}`}>
          <section>
            <h2>モデル</h2>
            {status.kind === "ready" ? (
              <dl>
                <dt>名前</dt>
                <dd>{status.info.title}</dd>
                <dt>作者</dt>
                <dd>{status.info.author}</dd>
                <dt>VRM</dt>
                <dd>{status.info.specVersion}</dd>
                <dt>表情</dt>
                <dd className="avatar-small">
                  {status.info.expressions.length} 個(
                  {status.info.expressions.filter((n) => PRESETS.has(n)).join(" ")} ほか)
                </dd>
              </dl>
            ) : (
              <p className="avatar-small">未読み込み</p>
            )}
            <input type="file" accept=".vrm" onChange={onPickModel} />
          </section>

          <section>
            <h2>状態(いま: {behavior.state})</h2>
            <div className="avatar-buttons">
              {(Object.keys(STATE_LABEL) as (keyof typeof STATE_LABEL)[]).map((st) => (
                <button
                  key={st}
                  className={st === behavior.state ? "on" : ""}
                  onClick={() =>
                    sendCue(
                      st === "error"
                        ? { kind: "state", state: st, detail: "(試験)LLM に接続できません。" }
                        : { kind: "state", state: st },
                    )
                  }
                >
                  {STATE_LABEL[st]}
                </button>
              ))}
              <button onClick={() => behavior.sleepNow()}>居眠り</button>
              <button
                onClick={() =>
                  sendCue({ kind: "bubble", text: "お呼びでしょうか、マスター。", final: true })
                }
              >
                吹き出し
              </button>
              <button onClick={() => sendCue({ kind: "nod" })}>うなずき</button>
            </div>
          </section>

          <section>
            <h2>表情</h2>
            <div className="avatar-buttons">
              {EMOTIONS.map((e) => (
                <button key={e} className={e === emotion ? "on" : ""} onClick={() => setEmotion(e)}>
                  {EMOTION_LABEL[e]}
                </button>
              ))}
            </div>
            <label>
              強さ {weight.toFixed(2)}
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={weight}
                onChange={(e) => setWeight(Number(e.target.value))}
              />
            </label>
            <label className="avatar-check">
              <input type="checkbox" checked={blink} onChange={(e) => setBlink(e.target.checked)} />
              自動まばたき
            </label>
          </section>

          <section>
            <h2>口パク(文字から)</h2>
            <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} />
            <label>
              1拍 {moraSec.toFixed(2)} 秒
              <input
                type="range"
                min={0.06}
                max={0.3}
                step={0.01}
                value={moraSec}
                onChange={(e) => setMoraSec(Number(e.target.value))}
              />
            </label>
            <button onClick={() => stageRef.current?.speak(text, moraSec)}>話す</button>
          </section>

          <section>
            <h2>口パク(音声の大きさから)</h2>
            <input type="file" accept="audio/*" onChange={onPickAudio} />
            {audioUrl && (
              <audio
                ref={audioRef}
                src={audioUrl}
                controls
                onPlay={onAudioPlay}
                onPause={() => stageRef.current?.attachAudio(null)}
                onEnded={() => stageRef.current?.attachAudio(null)}
              />
            )}
          </section>
        </aside>
      )}
    </div>
  );
}
