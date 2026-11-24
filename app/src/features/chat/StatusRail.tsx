import type { VoiceStatus } from "../voice/useVoice";
import { Character, Health } from "./types";

/**
 * ステータスレール(画面上部)はこのアプリの署名的要素:sidecarアーキテクチャの
 * 「CORE(コアプロセス)/LLM(推論サーバ)」というリンク状態の真実をそのまま可視化する。
 */
export function StatusRail(props: {
  coreState: "linked" | "connecting" | "error";
  health: Health | null;
  characters: Character[];
  active: string;
  onSwitchCharacter: (id: string) => void;
  onOpenSettings: () => void;
  voice: VoiceStatus | null;
  onToggleVoice: () => void;
}) {
  const { coreState, health, characters, active, onSwitchCharacter, onOpenSettings } = props;
  const { voice, onToggleVoice } = props;
  // 声: オフ=灰、オンで VOICEVOX(同梱 CORE かアプリ)が使える=水色、オンなのに使えない=黄
  const voiceState = !voice?.enabled ? "connecting" : voice.available ? "linked" : "offline";
  return (
    <header className="rail">
      <span className="brand">SENTINEL</span>
      <span className={`link link--${coreState}`}>
        <i className="dot" /> CORE {coreState === "linked" ? "LINK" : coreState.toUpperCase()}
      </span>
      <span className={`link link--${health?.llm_reachable ? "linked" : "offline"}`}>
        <i className="dot" /> LLM {health?.llm_reachable ? "READY" : "OFFLINE"}
      </span>
      {voice && (
        <button
          className={`link link--${voiceState} rail__toggle`}
          onClick={onToggleVoice}
          title={voice.enabled ? "声をオフにする" : "声をオンにする"}
        >
          <i className="dot" /> VOICE{" "}
          {!voice.enabled ? "OFF" : voice.available ? "ON" : "NO ENGINE"}
        </button>
      )}
      <span className="spacer" />
      <label className="char">
        <span>character</span>
        <select value={active} onChange={(e) => onSwitchCharacter(e.target.value)}>
          <option value="none">汎用モード</option>
          {characters.map((c) => (
            <option key={c.id} value={c.id}>
              {c.display_name}
            </option>
          ))}
        </select>
      </label>
      <button className="gear" onClick={onOpenSettings} aria-label="設定" title="設定">
        <GearIcon />
      </button>
    </header>
  );
}

/** 歯車アイコン(アイコン集に頼らず、線の SVG で描く) */
function GearIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="3.2" stroke="currentColor" strokeWidth="1.8" />
      <path
        d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.03 1.56V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1.11-1.56 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.56-1.03H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 8.94a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34H9a1.7 1.7 0 0 0 1-1.56V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.56 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87V9c.26.6.86 1 1.51 1H21a2 2 0 1 1 0 4h-.09c-.65 0-1.25.4-1.51 1Z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  );
}
