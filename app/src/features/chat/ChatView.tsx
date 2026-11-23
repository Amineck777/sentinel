import { useEffect, useRef, useState } from "react";
import { useVoice } from "../voice/useVoice";
import { VoicePlayer } from "../voice/voicePlayer";
import { SettingsPanel } from "../settings/SettingsPanel";
import { isTauri } from "../settings/shellSettings";
import { Composer } from "./Composer";
import { MessageLog } from "./MessageLog";
import { StatusRail } from "./StatusRail";
import { useChat } from "./useChat";
import { useCore } from "./useCore";

/** チャット画面。状態は useCore(接続・キャラ)と useChat(会話)に分離。 */
export function ChatView() {
  const { core, coreState, ready, health, characters, active, activateCharacter } = useCore();
  // 音を鳴らす係は画面に1つだけ(再描画で作り直さない)
  const [player] = useState(() => new VoicePlayer());
  const { msgs, send, greet, resetSession } = useChat(core, player);
  const voice = useVoice(core, active, player);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // 起動したら、キャラから先に挨拶する(1回だけ。汎用モードではコアが何もしない)
  const greetedRef = useRef(false);
  useEffect(() => {
    if (!ready || greetedRef.current) return;
    greetedRef.current = true;
    void greet();
  }, [ready, greet]);

  // トレイの「設定…」からも開けるようにする
  useEffect(() => {
    if (!isTauri()) return;
    let unlisten: (() => void) | undefined;
    let cancelled = false;
    void import("@tauri-apps/api/event").then(({ listen }) =>
      listen("settings://open", () => setSettingsOpen(true)).then((u) => {
        if (cancelled) u();
        else unlisten = u;
      }),
    );
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, []);

  const switchCharacter = async (id: string) => {
    player.stop();
    await activateCharacter(id);
    resetSession(); // キャラ切替時は新セッション(仕様 §16.3)
    await greet(); // 切り替えたキャラから挨拶する
  };

  return (
    <div className="shell">
      <StatusRail
        coreState={coreState}
        health={health}
        characters={characters}
        active={active}
        onSwitchCharacter={(id) => void switchCharacter(id)}
        onOpenSettings={() => setSettingsOpen(true)}
        voice={voice.status}
        onToggleVoice={() => voice.status && void voice.setEnabled(!voice.status.enabled)}
      />
      <MessageLog msgs={msgs} />
      <Composer disabled={!core} onSend={(content) => void send(content)} />
      {settingsOpen && (
        <SettingsPanel
          onClose={() => setSettingsOpen(false)}
          coreState={coreState}
          health={health}
          voice={voice}
          characterName={characters.find((c) => c.id === active)?.display_name ?? "汎用モード"}
        />
      )}
    </div>
  );
}
