import { useEffect, useState } from "react";
import { api, CoreInfo, resolveCore } from "../../api/client";
import { Character, Health } from "./types";

const HEALTH_POLL_MS = 15_000;

/**
 * コア接続の確立(handshake or devフォールバック)と、
 * ステータスレールに出す情報(health / Character一覧)の取得。
 * health は定期ポーリングし、LLM(Ollama)の後から起動/停止に表示が追従する。
 */
export function useCore() {
  const [core, setCore] = useState<CoreInfo | null>(null);
  const [coreError, setCoreError] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthFailed, setHealthFailed] = useState(false);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [active, setActive] = useState<string>("none");
  // キャラ一覧(と前回のキャラ)を読み終えたか。起動時の挨拶はこの後に行う
  const [ready, setReady] = useState(false);

  // --- 接続確立+Character一覧 ---
  useEffect(() => {
    let cancelled = false;
    resolveCore()
      .then(async (c) => {
        if (cancelled) return;
        setCore(c);
        const cs = await api<{ active: string | null; characters: Character[] }>(c, "/characters");
        if (cancelled) return;
        setCharacters(cs.characters.filter((x) => x.valid));
        setActive(cs.active ?? "none");
        setReady(true);
      })
      .catch((e) => setCoreError(String(e)));
    return () => {
      cancelled = true;
    };
  }, []);

  // --- health ポーリング(実装方針 §3: 接続失敗はステータスレールで可視化)---
  useEffect(() => {
    if (!core) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const h = await api<Health>(core, "/system/health");
        if (!cancelled) {
          setHealth(h);
          setHealthFailed(false);
        }
      } catch {
        if (!cancelled) {
          setHealth(null);
          setHealthFailed(true); // コア自体に届かない → CORE を ERROR 表示に
        }
      }
    };
    void tick();
    const id = setInterval(() => void tick(), HEALTH_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [core]);

  const activateCharacter = async (id: string) => {
    if (!core) return;
    await api(core, `/characters/${id}/activate`, { method: "POST" });
    setActive(id);
  };

  const coreState = coreError || healthFailed ? "error" : core ? "linked" : "connecting";

  return { core, coreState, ready, health, characters, active, activateCharacter } as const;
}
