import { useEffect } from "react";
import "./settings.css";
import type { Health } from "../chat/types";
import { isTauri, pickVrmFile, useShellSettings } from "./shellSettings";

/** 右上のギアから開く設定画面。窓の右側に重ねて出す */
export function SettingsPanel(props: {
  onClose: () => void;
  coreState: "linked" | "connecting" | "error";
  health: Health | null;
}) {
  const { onClose, coreState, health } = props;
  const { settings, error, change } = useShellSettings();

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
                アバターを掴むと窓ごと動かせます。ダブルクリックで表情・口パクの試験パネル。
              </p>
            </>
          )}
          {error && <p className="settings__error">{error}</p>}
        </section>

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
            <dt>コアの版</dt>
            <dd>{health?.version ?? "-"}</dd>
          </dl>
          <p className="settings__note">
            LLM の接続先はコアの config.yaml(llm.endpoint)で変えます。
          </p>
        </section>

        <section>
          <h2>ホットキー</h2>
          <p>
            <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Space</kbd> でこの窓を出し入れ(使えないときは{" "}
            <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Space</kbd>)
          </p>
          <p className="settings__note">変更は環境変数 SENTINEL_HOTKEY(設定画面での変更は今後)。</p>
        </section>
      </aside>
    </div>
  );
}
