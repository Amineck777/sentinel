import { useEffect, useState } from "react";
import type { Voice } from "./useVoice";

const SAMPLE = "おかえりなさいませ、マスター。今日もお疲れさまでした。";

// コアが返すエンジン名 → 画面に出す名前。
// voicevox_core = コアに同梱した VOICEVOX CORE(アプリ不要)、voicevox = 別に起動した VOICEVOX アプリ
const ENGINE_LABELS: Record<string, string> = {
  voicevox_core: "VOICEVOX CORE 同梱版(アプリ不要)",
  voicevox: "VOICEVOX アプリ",
};

/** 設定画面の「声」。オン/オフ、キャラごとの声選び、試聴 */
export function VoiceSection(props: { voice: Voice; characterName: string }) {
  const { voice, characterName } = props;
  const { status, speakers, error, loadSpeakers } = voice;
  const [sample, setSample] = useState(SAMPLE);

  // 設定を開いたら話者の一覧を取りに行く(VOICEVOX を後から起動しても開き直せば出る)
  useEffect(() => void loadSpeakers(), [loadSpeakers]);

  const selected = speakers?.find((s) => s.styles.some((st) => st.id === status?.speaker_id));
  // 同梱の CORE なら「起動してください」ではなく「セットアップしてください」と案内する
  const bundled = status?.engine === "voicevox_core";

  return (
    <section>
      <h2>声</h2>
      {!status ? (
        <p className="settings__note">読み込み中…</p>
      ) : (
        <>
          <label className="settings__row">
            <span>返事を声で読み上げる</span>
            <input
              type="checkbox"
              checked={status.enabled}
              onChange={(e) => void voice.setEnabled(e.target.checked)}
            />
          </label>
          <dl className="settings__info">
            <dt>エンジン</dt>
            <dd>
              {status.engine ? (ENGINE_LABELS[status.engine] ?? status.engine) : "なし"} /{" "}
              {status.available ? "使えます" : "使えません"}
            </dd>
          </dl>

          <div className="settings__field">
            <span>{characterName} の声</span>
            {speakers ? (
              <select
                className="settings__select"
                value={status.speaker_id ?? ""}
                onChange={(e) =>
                  void voice.setSpeaker(e.target.value === "" ? null : Number(e.target.value))
                }
              >
                <option value="">(既定: キャラ設定、無ければ config の声 = 暁記ミタマ)</option>
                {speakers.map((sp) => (
                  <optgroup key={sp.name} label={sp.name}>
                    {sp.styles.map((st) => (
                      <option key={st.id} value={st.id}>
                        {sp.name} / {st.name}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            ) : (
              <p className="settings__note">
                {bundled
                  ? "VOICEVOX CORE の準備ができると、ここで声を選べます(scripts/setup_voicevox_core.py)。"
                  : "VOICEVOX を起動すると、ここで声を選べます。"}
              </p>
            )}
            <input
              className="settings__input"
              value={sample}
              onChange={(e) => setSample(e.target.value)}
              aria-label="試聴する文"
            />
            <div className="settings__buttons">
              <button
                className="settings__btn"
                disabled={!status.available}
                onClick={() => void voice.preview(sample, status.speaker_id)}
              >
                試聴
              </button>
              <button className="settings__btn" onClick={() => void loadSpeakers()}>
                再読み込み
              </button>
            </div>
            {selected && (
              <p className="settings__note">
                クレジット: <code>{selected.credit}</code>
                (声を録音・公開するときは表記が必要です。手元で聞くだけなら不要)
              </p>
            )}
          </div>

          <p className="settings__note">
            声は{" "}
            <a href="https://voicevox.hiroshiba.jp/" target="_blank" rel="noreferrer">
              VOICEVOX
            </a>{" "}
            で作ります。同梱の VOICEVOX CORE を入れればアプリの起動は要らず、入れていなければ
            VOICEVOX アプリを起動しておくと使えます(どちらも GPU ではなく CPU で動くので、LLM
            の邪魔をしません)。
            キャラごとに利用規約が違うので、配信や公開に使う前にそのキャラの規約を確認してください。
          </p>
        </>
      )}
      {error && <p className="settings__error">{error}</p>}
    </section>
  );
}
