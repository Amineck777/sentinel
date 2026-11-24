// 頭の上の吹き出し。話している文・考え中の「…」・困ったときの説明・居眠りの「z」を出す。
import type { BubbleView } from "./useAvatarBehavior";
import { HIT_CLASS } from "./useClickThrough";

export function Bubble({ view, onOpenChat }: { view: BubbleView; onOpenChat?: () => void }) {
  if (!view) return null;
  if (view.kind === "sleep") {
    return (
      <div className="avatar-zz" aria-label="居眠り中">
        <span>z</span>
        <span>z</span>
      </div>
    );
  }
  if (view.kind === "thinking") {
    return (
      <div className="avatar-bubble avatar-bubble--small" role="status" aria-label="考え中">
        <span className="avatar-dots">
          <i />
          <i />
          <i />
        </span>
      </div>
    );
  }
  if (view.kind === "error") {
    return (
      <div className={`avatar-bubble avatar-bubble--error ${HIT_CLASS}`} role="alert">
        <p>申し訳ありません。今は考える力が使えないようです。</p>
        <p className="avatar-bubble__detail">{view.text}</p>
        {onOpenChat && (
          <button className="avatar-bubble__btn" onClick={onOpenChat}>
            チャットを開く
          </button>
        )}
      </div>
    );
  }
  return (
    <div className={`avatar-bubble ${HIT_CLASS}`} role="status" onClick={onOpenChat}>
      {view.speaking && (
        <div className="avatar-bubble__head">
          <SpeakerIcon />
          <span>読み上げ中</span>
        </div>
      )}
      <p className="avatar-bubble__text">{view.text}</p>
    </div>
  );
}

function SpeakerIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M11 5 6 9H2v6h4l5 4V5z" stroke="currentColor" strokeWidth="2" />
      <path d="M15.5 8.5a5 5 0 0 1 0 7" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}
