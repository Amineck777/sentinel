/**
 * シェル(Tauri)側の設定の読み書き。保存と窓への反映は Rust(src-tauri/src/settings.rs)が受け持つ。
 * ブラウザ開発では Tauri が無いので、設定は読めない(null)。
 */
import { useCallback, useEffect, useState } from "react";

export type ShellSettings = {
  avatarVisible: boolean;
  avatarAlwaysOnTop: boolean;
  avatarModelPath: string | null;
  /** 体以外の透明な部分のクリックを下のアプリへ通す */
  avatarClickThrough: boolean;
  /** 頭の上に吹き出しを出す */
  avatarBubble: boolean;
  /** 話し終えてから吹き出しが消えるまでの秒数 */
  avatarBubbleSeconds: number;
  /** マウスカーソルを目で追う */
  avatarFollowCursor: boolean;
  /** 表情の強さ 0〜1 */
  avatarEmotionStrength: number;
  /** 何分操作が無いと居眠りするか。0 で居眠りしない */
  avatarSleepMinutes: number;
  /** ホットキーでチャットを開くとき、アバターの横に出す */
  chatBesideAvatar: boolean;
};

/** Rust 側(src-tauri/src/settings.rs)の既定値と同じ。ブラウザ開発ではこれで動く */
export const DEFAULT_SHELL_SETTINGS: ShellSettings = {
  avatarVisible: false,
  avatarAlwaysOnTop: true,
  avatarModelPath: null,
  avatarClickThrough: true,
  avatarBubble: true,
  avatarBubbleSeconds: 6,
  avatarFollowCursor: true,
  avatarEmotionStrength: 0.45,
  avatarSleepMinutes: 10,
  chatBesideAvatar: true,
};

export const isTauri = () => "__TAURI_INTERNALS__" in window;

export async function getSettings(): Promise<ShellSettings> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<ShellSettings>("get_settings");
}

export async function updateSettings(settings: ShellSettings): Promise<ShellSettings> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<ShellSettings>("update_settings", { settings });
}

/** 設定が変わったら呼ばれる(どの窓で変えても、トレイから変えても届く)。戻り値で購読をやめる */
export async function onSettingsChanged(cb: (s: ShellSettings) => void): Promise<() => void> {
  const { listen } = await import("@tauri-apps/api/event");
  return listen<ShellSettings>("settings://changed", (e) => cb(e.payload));
}

/** 設定済みのモデルファイルの中身。Rust はバイト列のまま返すので ArrayBuffer で届く */
export async function readAvatarModel(): Promise<ArrayBuffer> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<ArrayBuffer>("read_avatar_model");
}

/** 実際に登録できたホットキー(Alt+Space が他のアプリに取られていれば次の候補)。無ければ null */
export async function getHotkey(): Promise<string | null> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<string | null>("get_hotkey");
}

/** .vrm を選ぶダイアログ。キャンセルなら null */
export async function pickVrmFile(): Promise<string | null> {
  const { open } = await import("@tauri-apps/plugin-dialog");
  const picked = await open({
    multiple: false,
    directory: false,
    filters: [{ name: "VRM", extensions: ["vrm"] }],
  });
  return typeof picked === "string" ? picked : null;
}

/** 設定の現在値と、変更する関数。失敗したらメッセージを error に入れる */
export function useShellSettings() {
  const [settings, setSettings] = useState<ShellSettings | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isTauri()) return;
    let unlisten: (() => void) | undefined;
    let cancelled = false;
    getSettings()
      .then((s) => !cancelled && setSettings(s))
      .catch((e: unknown) => setError(String(e)));
    void onSettingsChanged((s) => setSettings(s)).then((u) => {
      if (cancelled) u();
      else unlisten = u;
    });
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, []);

  const change = useCallback(
    async (patch: Partial<ShellSettings>) => {
      if (!settings) return;
      try {
        setSettings(await updateSettings({ ...settings, ...patch }));
        setError(null);
      } catch (e) {
        setError(String(e));
      }
    },
    [settings],
  );

  return { settings, error, change };
}
