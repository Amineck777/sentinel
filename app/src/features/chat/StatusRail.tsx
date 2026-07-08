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
}) {
  const { coreState, health, characters, active, onSwitchCharacter } = props;
  return (
    <header className="rail">
      <span className="brand">SENTINEL</span>
      <span className={`link link--${coreState}`}>
        <i className="dot" /> CORE {coreState === "linked" ? "LINK" : coreState.toUpperCase()}
      </span>
      <span className={`link link--${health?.llm_reachable ? "linked" : "offline"}`}>
        <i className="dot" /> LLM {health?.llm_reachable ? "READY" : "OFFLINE"}
      </span>
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
    </header>
  );
}
