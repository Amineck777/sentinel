/**
 * クリック透過(ADR 0114)。透明な窓でも、そのままでは「何も描いていない部分」がクリックを吸う。
 *
 * 60ms ごとに OS からカーソルの位置を聞き(Rust の avatar_cursor)、
 *   - 体の上(描いた画素が不透明)や吹き出し・ボタンの上 → クリックを受ける
 *   - それ以外 → setIgnoreCursorEvents(true) で下のアプリへ通す
 * を切り替える。透過中の窓にはマウスのイベントが届かないので、DOM のイベントでは判定できない。
 * ついでに、カーソルの位置をアバターの視線にも使う(窓の外にあっても目で追える)。
 */
import { useEffect } from "react";
import type { AvatarStage } from "./avatarStage";

const POLL_MS = 60;

/** 体以外でクリックを受けたい要素(吹き出しのボタン・試験パネルなど)に付ける印 */
export const HIT_CLASS = "avatar-hit";

export function useClickThrough(
  stage: () => AvatarStage | null,
  canvas: () => HTMLCanvasElement | null,
  options: { enabled: boolean; active: boolean },
) {
  const { enabled, active } = options;
  useEffect(() => {
    if (!active) return;
    let stopped = false;
    let ignoring: boolean | null = null;
    let busy = false;

    const setIgnore = async (ignore: boolean) => {
      if (ignore === ignoring) return;
      ignoring = ignore;
      const { getCurrentWindow } = await import("@tauri-apps/api/window");
      await getCurrentWindow().setIgnoreCursorEvents(ignore);
    };

    const tick = async () => {
      if (busy || stopped) return;
      busy = true;
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        const pos = await invoke<{ x: number; y: number }>("avatar_cursor");
        const st = stage();
        const cv = canvas();
        if (st && cv) {
          const r = cv.getBoundingClientRect();
          st.setCursor({ x: pos.x - r.left, y: pos.y - r.top });
        }
        if (!enabled) {
          await setIgnore(false);
          return;
        }
        const inside =
          pos.x >= 0 && pos.y >= 0 && pos.x < window.innerWidth && pos.y < window.innerHeight;
        let hit = false;
        if (inside) {
          const el = document.elementFromPoint(pos.x, pos.y);
          if (el && el === cv && st) {
            const r = cv.getBoundingClientRect();
            hit = st.hitTest(pos.x - r.left, pos.y - r.top);
          } else if (el?.closest(`.${HIT_CLASS}`)) {
            hit = true;
          }
        }
        await setIgnore(!hit);
      } catch {
        // 窓が閉じかけているときなど。次の回でやり直す
      } finally {
        busy = false;
      }
    };

    const id = window.setInterval(() => void tick(), POLL_MS);
    return () => {
      stopped = true;
      window.clearInterval(id);
      // 止めるときは必ずクリックを受ける状態へ戻す(透過したまま操作できなくなるのを防ぐ)
      void import("@tauri-apps/api/window").then(({ getCurrentWindow }) =>
        getCurrentWindow().setIgnoreCursorEvents(false),
      );
    };
  }, [stage, canvas, enabled, active]);
}
