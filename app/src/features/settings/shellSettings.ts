/**
 * シェル(Tauri)側の設定の読み書き。保存と窓への反映は Rust(src-tauri/src/settings.rs)が受け持つ。
 * ブラウザ開発では Tauri が無いので、設定は読めない(null)。
 */
import { useCallback, useEffect, useState } from "react";

export type ShellSettings = {
  avatarVisible: boolean;
  avatarAlwaysOnTop: boolean;
  avatarModelPath: string | null;
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
