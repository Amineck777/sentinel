import { useEffect, useState } from "react";
import { api, CoreInfo, resolveCore } from "../../api/client";
import { Character, Health } from "./types";

/**
 * コア接続の確立(handshake or devフォールバック)と、
 * ステータスレールに出す情報(health / Character一覧)の取得。
 */
export function useCore() {
  const [core, setCore] = useState<CoreInfo | null>(null);
  const [coreError, setCoreError] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [active, setActive] = useState<string>("none");

  useEffect(() => {
    let cancelled = false;
    resolveCore()
      .then(async (c) => {
        if (cancelled) return;
        setCore(c);
        const h = await api<Health>(c, "/system/health");
        const cs = await api<{ active: string | null; characters: Character[] }>(c, "/characters");
        if (cancelled) return;
        setHealth(h);
        setCharacters(cs.characters.filter((x) => x.valid));
        setActive(cs.active ?? "none");
      })
      .catch((e) => setCoreError(String(e)));
    return () => {
      cancelled = true;
    };
  }, []);

  const activateCharacter = async (id: string) => {
    if (!core) return;
    await api(core, `/characters/${id}/activate`, { method: "POST" });
    setActive(id);
  };

  const coreState = coreError ? "error" : core ? "linked" : "connecting";

  return { core, coreState, health, characters, active, activateCharacter } as const;
}
