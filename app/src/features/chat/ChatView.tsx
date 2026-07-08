import { Composer } from "./Composer";
import { MessageLog } from "./MessageLog";
import { StatusRail } from "./StatusRail";
import { useChat } from "./useChat";
import { useCore } from "./useCore";

/** チャット画面。状態は useCore(接続・キャラ)と useChat(会話)に分離。 */
export function ChatView() {
  const { core, coreState, health, characters, active, activateCharacter } = useCore();
  const { msgs, send, resetSession } = useChat(core);

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
      />
      <MessageLog msgs={msgs} />
      <Composer disabled={!core} onSend={(content) => void send(content)} />
    </div>
  );
}
