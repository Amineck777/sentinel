/**
 * コアAPIクライアント(実装方針 §1/§2)。
 *
 * 接続先の解決:
 *  - Tauri内: Rustの `get_core_info` コマンドをポーリングし、handshake由来の
 *    port/token を取得(sidecar起動完了まで数秒かかるためリトライ)
 *  - ブラウザ開発: 環境変数(既定 http://127.0.0.1:8765 / dev-token)へフォールバック
 *
 * 本格実装ではここを openapi-typescript 生成型に置き換える(仕様 §5.1 generated/)。
 */

import type { CoreEmotion } from "../features/avatar/cueChannel";
import type { AudioChunk } from "../features/voice/voicePlayer";

export type CoreInfo = { baseUrl: string; token: string };

// WSイベント契約(仕様 §7)。`type` の追加のみ許可(前方互換)。
// 未知の type はハンドラ側で単に無視されるため、ここには既知のもののみ列挙する。
export type StreamEvent =
  | { type: "token"; session_id: string; delta: string }
  | { type: "message_done"; session_id: string; message_id: string }
  | { type: "notice"; level: "info" | "warn" | "error"; text: string }
  // 返答の読み上げ(仕様 §18.4)。文ごとに1つ。turn が新しくなったら前のターンの音声は捨てる
  | ({ type: "audio_chunk"; session_id: string } & AudioChunk)
  | { type: "audio_done"; session_id: string; turn: number }
  // 文ごとの表情(アバター用)。変わったときだけ届く
  | { type: "emotion"; session_id: string; emotion: CoreEmotion }
  | { type: "approval_required"; approval_id: string; risk: string; summary: string }; // Phase 2予約

const isTauri = () => "__TAURI_INTERNALS__" in window;

async function tauriCoreInfo(): Promise<CoreInfo> {
  const { invoke } = await import("@tauri-apps/api/core");
  for (let i = 0; i < 40; i++) {
    const info = await invoke<{ port: number; token: string } | null>("get_core_info");
    if (info) return { baseUrl: `http://127.0.0.1:${info.port}`, token: info.token };
    await new Promise((r) => setTimeout(r, 250)); // sidecar起動待ち(最大10秒)
  }
  throw new Error("core handshake timeout");
}

export async function resolveCore(): Promise<CoreInfo> {
  if (isTauri()) return tauriCoreInfo();
  return {
    baseUrl: import.meta.env.VITE_CORE_URL ?? "http://127.0.0.1:8765",
    token: import.meta.env.VITE_CORE_TOKEN ?? "dev-token",
  };
}

export async function api<T>(core: CoreInfo, path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${core.baseUrl}/v1${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Sentinel-Token": core.token,
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json() as Promise<T>;
}

export function openStream(core: CoreInfo, onEvent: (e: StreamEvent) => void): () => void {
  const url = `${core.baseUrl.replace("http", "ws")}/v1/stream?token=${core.token}`;
  let ws: WebSocket | null = null;
  let closed = false;

  const connect = () => {
    ws = new WebSocket(url);
    ws.onmessage = (m) => onEvent(JSON.parse(m.data) as StreamEvent);
    ws.onclose = () => {
      if (!closed) setTimeout(connect, 1000); // 自動再接続(コア再起動に追従)
    };
  };
  connect();
  return () => {
    closed = true;
    ws?.close();
  };
}
