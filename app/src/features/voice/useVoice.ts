import { useCallback, useEffect, useState } from "react";
import { api, type CoreInfo } from "../../api/client";
import type { Clip, VoicePlayer } from "./voicePlayer";

export type VoiceStatus = {
  enabled: boolean;
  engine: string | null;
  /** エンジン(VOICEVOX)に繋がるか */
  available: boolean;
  /** 今のキャラの声(話者・スタイルID)。null ならエンジンの最初の声 */
  speaker_id: number | null;
  character_id: string | null;
};

export type VoiceSpeaker = {
  name: string;
  /** 生成音声を公開するときのクレジット表記(例: VOICEVOX:冥鳴ひまり) */
  credit: string;
  styles: { id: number; name: string }[];
};

/**
 * 声(読み上げ)の設定。オン/オフと声の選択はコアが保存する(キャラごと)。
 * active(今のキャラ)が変わったら、そのキャラの声を読み直す。
 */
export function useVoice(core: CoreInfo | null, active: string, player: VoicePlayer) {
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [speakers, setSpeakers] = useState<VoiceSpeaker[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!core) return;
    try {
      setStatus(await api<VoiceStatus>(core, "/voice"));
    } catch (e) {
      setError(String(e));
    }
  }, [core]);

  // 起動時とキャラ切替時に、そのキャラの声の設定を読む
  useEffect(() => {
    if (!core) return;
    let cancelled = false;
    api<VoiceStatus>(core, "/voice")
      .then((s) => !cancelled && setStatus(s))
      .catch((e: unknown) => !cancelled && setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, [core, active]);

  const loadSpeakers = useCallback(async () => {
    if (!core) return;
    try {
      const r = await api<{ speakers: VoiceSpeaker[] }>(core, "/voice/speakers");
      setSpeakers(r.speakers);
      setError(null);
    } catch {
      setSpeakers(null);
      setError("VOICEVOX に繋がりません。VOICEVOX を起動してから開き直してください。");
    }
    void refresh();
  }, [core, refresh]);

  const patch = async (body: Record<string, unknown>) => {
    if (!core) return;
    try {
      setStatus(
        await api<VoiceStatus>(core, "/voice", { method: "PATCH", body: JSON.stringify(body) }),
      );
    } catch (e) {
      setError(String(e));
    }
  };

  const setEnabled = async (enabled: boolean) => {
    if (!enabled) player.stop();
    await patch({ enabled });
  };

  const setSpeaker = (id: number | null) =>
    patch(id === null ? { clear_speaker: true } : { speaker_id: id });

  const preview = async (text: string, speakerId?: number | null) => {
    if (!core) return;
    try {
      const clip = await api<Omit<Clip, "text">>(core, "/voice/preview", {
        method: "POST",
        body: JSON.stringify({ text, speaker_id: speakerId ?? null }),
      });
      player.play({ ...clip, text });
      setError(null);
    } catch {
      setError("試聴できませんでした。VOICEVOX が起動しているか確認してください。");
    }
  };

  return { status, speakers, error, refresh, loadSpeakers, setEnabled, setSpeaker, preview };
}

export type Voice = ReturnType<typeof useVoice>;
