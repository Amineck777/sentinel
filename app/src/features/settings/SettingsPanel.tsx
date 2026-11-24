import { useEffect, useState } from "react";
import "./settings.css";
import type { Health } from "../chat/types";
import { VoiceSection } from "../voice/VoiceSection";
import type { Voice } from "../voice/useVoice";
import { getHotkey, isTauri, pickVrmFile, useShellSettings } from "./shellSettings";

/** 右上のギアから開く設定画面。窓の右側に重ねて出す */
export function SettingsPanel(props: {
  onClose: () => void;
  coreState: "linked" | "connecting" | "error";
  health: Health | null;
  voice: Voice;
  characterName: string;
}) {
  const { onClose, coreState, health, voice, characterName } = props;
  const { settings, error, change } = useShellSettings();
  const [hotkey, setHotkey] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    if (isTauri()) void getHotkey().then(setHotkey, () => setHotkey(null));
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const pickModel = async () => {
    const path = await pickVrmFile();
    if (path) await change({ avatarModelPath: path });
  };

  return (
    <div className="settings-backdrop" onMouseDown={onClose}>
      <aside
        className="settings"
        role="dialog"
        aria-label="設定"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header className="settings__head">
          <h1>設定</h1>
          <button className="settings__close" onClick={onClose} aria-label="閉じる">
            ×
          </button>
        </header>

        <section>
          <h2>アバター</h2>
          {!isTauri() ? (
            <p className="settings__note">
              デスクトップアプリでのみ変更できます。ブラウザでは{" "}
              <a href="/avatar.html" target="_blank" rel="noreferrer">
                avatar.html
              </a>{" "}
              で試せます。
            </p>
          ) : !settings ? (
            <p className="settings__note">読み込み中…</p>
          ) : (
            <>
              <label className="settings__row">
                <span>アバターを表示する</span>
                <input
                  type="checkbox"
                  checked={settings.avatarVisible}
                  onChange={(e) => void change({ avatarVisible: e.target.checked })}
                />
              </label>
              <label className="settings__row">
                <span>常に最前面に表示</span>
                <input
                  type="checkbox"
                  checked={settings.avatarAlwaysOnTop}
                  onChange={(e) => void change({ avatarAlwaysOnTop: e.target.checked })}
                />
              </label>
              <div className="settings__field">
                <span>モデル(.vrm)</span>
                <code className="settings__path">{settings.avatarModelPath ?? "未設定"}</code>
                <div className="settings__buttons">
                  <button className="settings__btn" onClick={() => void pickModel()}>
                    ファイルを選ぶ…
                  </button>
                  {settings.avatarModelPath && (
                    <button
                      className="settings__btn"
                      onClick={() => void change({ avatarModelPath: null })}
                    >
                      解除
                    </button>
                  )}
                </div>
                <p className="settings__note">
                  モデルは手元のファイルを読むだけで、アプリやリポジトリには取り込みません。
                  配布規約(再配布・商用・表現の制限)を守って使ってください。
                </p>
              </div>
              <p className="settings__note">
                アバターを掴むと窓ごと動かせます。ダブルクリックで状態・表情・口パクの試験パネル。
              </p>

              <h3 className="settings__sub">ふるまい</h3>
              <label className="settings__row">
                <span>体以外はクリックを下のアプリへ通す</span>
                <input
                  type="checkbox"
                  checked={settings.avatarClickThrough}
                  onChange={(e) => void change({ avatarClickThrough: e.target.checked })}
                />
              </label>
              <label className="settings__row">
                <span>マウスを目で追う</span>
                <input
                  type="checkbox"
                  checked={settings.avatarFollowCursor}
                  onChange={(e) => void change({ avatarFollowCursor: e.target.checked })}
                />
              </label>
              <label className="settings__row">
                <span>頭の上に吹き出しを出す</span>
                <input
                  type="checkbox"
                  checked={settings.avatarBubble}
                  onChange={(e) => void change({ avatarBubble: e.target.checked })}
                />
              </label>
              <label className="settings__field">
                <span>吹き出しを消すまで: 話し終えてから {settings.avatarBubbleSeconds} 秒</span>
                <input
                  type="range"
                  min={2}
                  max={20}
                  step={1}
                  value={settings.avatarBubbleSeconds}
                  disabled={!settings.avatarBubble}
                  onChange={(e) => void change({ avatarBubbleSeconds: Number(e.target.value) })}
                />
              </label>
              <label className="settings__field">
                <span>表情の強さ: {Math.round(settings.avatarEmotionStrength * 100)}%</span>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={settings.avatarEmotionStrength}
                  onChange={(e) => void change({ avatarEmotionStrength: Number(e.target.value) })}
                />
              </label>
              <label className="settings__field">
                <span>
                  居眠りするまで:{" "}
                  {settings.avatarSleepMinutes === 0
                    ? "居眠りしない"
                    : `操作が無いまま ${settings.avatarSleepMinutes} 分`}
                </span>
                <input
                  type="range"
                  min={0}
                  max={60}
                  step={1}
                  value={settings.avatarSleepMinutes}
                  onChange={(e) => void change({ avatarSleepMinutes: Number(e.target.value) })}
                />
              </label>
              <p className="settings__note">
                深夜(0〜5 時)は 3 分で眠くなります。話しかけるか、アバターに触れると起きます。
                表情は返事の言葉から控えめに決めます(モデルが [joy]
                のような感情タグを書けば、そちらを優先)。
              </p>
            </>
          )}
          {error && <p className="settings__error">{error}</p>}
        </section>

        <VoiceSection voice={voice} characterName={characterName} />

        <section>
          <h2>接続</h2>
          <dl className="settings__info">
            <dt>コア</dt>
            <dd>
              {coreState === "linked"
                ? "接続中"
                : coreState === "connecting"
                  ? "接続待ち"
                  : "エラー"}
            </dd>
            <dt>LLM</dt>
            <dd>{health?.llm_reachable ? "応答あり" : "未接続(オフライン応答)"}</dd>
            <dt>モデル</dt>
            <dd>{health?.chat_model ?? "-"}</dd>
            <dt>コアの版</dt>
            <dd>{health?.version ?? "-"}</dd>
          </dl>
          <p className="settings__note">
            LLM の接続先はコアの config.yaml(llm.endpoint)で変えます。モデルはキャラごとに
            character.yaml の llm.model で決まり、無ければ config.yaml の llm.chat_model
            を使います。
          </p>
        </section>

        <section>
          <h2>ホットキー</h2>
          <p>
            {hotkey ? <kbd>{hotkey}</kbd> : hotkey === null ? "(登録できませんでした)" : "…"}{" "}
            でチャットを出し入れ
          </p>
          {settings && (
            <label className="settings__row">
              <span>チャットをアバターの横に出す</span>
              <input
                type="checkbox"
                checked={settings.chatBesideAvatar}
                onChange={(e) => void change({ chatBesideAvatar: e.target.checked })}
              />
            </label>
          )}
          <p className="settings__note">
            Alt+Space を他のアプリ(PowerToys Run など)が使っていると、Ctrl+Shift+Space →
            Ctrl+Alt+Space の順に代わりを使います。変更は環境変数
            SENTINEL_HOTKEY(設定画面での変更は今後)。
          </p>
        </section>
      </aside>
    </div>
  );
}
