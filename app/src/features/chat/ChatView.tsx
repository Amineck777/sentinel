import { useEffect, useState } from "react";
import { SettingsPanel } from "../settings/SettingsPanel";
import { isTauri } from "../settings/shellSettings";
import { Composer } from "./Composer";
import { MessageLog } from "./MessageLog";
import { StatusRail } from "./StatusRail";
import { useChat } from "./useChat";
import { useCore } from "./useCore";

/** チャット画面。状態は useCore(接続・キャラ)と useChat(会話)に分離。 */
export function ChatView() {
  const { core, coreState, health, characters, active, activateCharacter } = useCore();
  const { msgs, send, resetSession } = useChat(core);
  const [settingsOpen, setSettingsOpen] = useState(false);

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
    await activateCharacter(id);
    resetSession(); // キャラ切替時は新セッション(仕様 §16.3)
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
      />
      <MessageLog msgs={msgs} />
      <Composer disabled={!core} onSend={(content) => void send(content)} />
      {settingsOpen && (
        <SettingsPanel
          onClose={() => setSettingsOpen(false)}
          coreState={coreState}
          health={health}
        />
      )}
    </div>
  );
}
