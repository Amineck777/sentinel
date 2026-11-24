/**
 * アバターの「演出係」。チャット窓の中で会話の出来事を受け取り、アバターの状態を決めて
 * アバター窓へ送る(cueChannel)。状態の決め方は優先度の高い順に:
 *
 *   error(コアや LLM に繋がらない) > speaking(声を鳴らしている・声なしで返事を見せている)
 *   > thinking(送ってから最初の返事が来るまで) > listening(マスターが入力中) > idle
 *
 * 居眠り(sleeping)は「操作が無い時間」をアバター窓が数えて自分で決める。
 * 声がオンのときの吹き出し・口パク・表情は、声と同じタイミングで lipsyncChannel から届くので、
 * ここでは「声が出ないとき」の吹き出しと表情だけを送る。
 */
import { onHello, sendCue, type AvatarCue, type AvatarState, type CoreEmotion } from "./cueChannel";

type BaseState = Exclude<AvatarState, "sleeping">;

export class AvatarDirector {
  private connectionError: string | null = null;
  private typing = false;
  private waiting = false; // 送信・挨拶から最初の返事まで
  private streaming = false; // 声なしで返事を流している
  private audioPlaying = false;
  private audioThisTurn = false;
  private voiceExpected = false;
  private replyText = "";
  private lastState: BaseState | null = null;
  private lastDetail: string | undefined;
  private bubbleTimer: number | undefined;
  private readonly unlisten: () => void;

  constructor() {
    // アバター窓が開き直したら、今の状態を送り直す
    this.unlisten = onHello(() => {
      this.lastState = null;
      this.update();
    });
  }

  dispose(): void {
    this.unlisten();
    window.clearTimeout(this.bubbleTimer);
  }

  /** null なら正常。文字列はアバターの吹き出しに出す説明 */
  setConnectionError(message: string | null): void {
    this.connectionError = message;
    this.update();
  }

  /** 声がオンで、エンジンにも繋がっているか(声で返事が届く見込みがあるか) */
  setVoiceExpected(on: boolean): void {
    this.voiceExpected = on;
  }

  setTyping(on: boolean): void {
    if (this.typing === on) return;
    this.typing = on;
    this.update();
  }

  /** マスターが送信した(挨拶の開始も同じ扱い。nod は送信のときだけ) */
  startTurn(withNod: boolean): void {
    if (withNod) sendCue({ kind: "nod" });
    this.waiting = true;
    this.streaming = false;
    this.audioThisTurn = false;
    this.replyText = "";
    this.update();
  }

  token(delta: string): void {
    this.replyText += delta;
    if (this.voiceExpected || this.audioThisTurn) return; // 声が来るのを待つ(thinking のまま)
    this.waiting = false;
    this.streaming = true;
    this.bubble(false);
    this.update();
  }

  emotion(emotion: CoreEmotion): void {
    // 声があるときは、その文を話し始めたときに表情を変える(lipsync 側)
    if (!this.voiceExpected && !this.audioThisTurn) sendCue({ kind: "emotion", emotion });
  }

  messageDone(): void {
    this.waiting = false;
    if (!this.audioThisTurn && this.replyText) {
      // 声が出なかった(声オフ・エンジン不調)ので、文字の吹き出しで見せる
      this.bubble(true);
      this.streaming = true;
      // 吹き出しを読む間だけ「話し中」の姿勢にして、その後は待機へ
      window.clearTimeout(this.bubbleTimer);
      this.bubbleTimer = window.setTimeout(
        () => {
          this.streaming = false;
          this.update();
        },
        Math.min(8000, 1500 + this.replyText.length * 60),
      );
    } else {
      this.streaming = false;
    }
    this.update();
  }

  /** 返事の音声が届いた(鳴り始めは audioActivity で知る) */
  audioArrived(): void {
    this.audioThisTurn = true;
  }

  /** 声が鳴り始めた / 鳴り終わった(VoicePlayer から) */
  audioActivity(playing: boolean): void {
    this.audioPlaying = playing;
    if (playing) this.waiting = false;
    this.update();
  }

  /** 生成が失敗したときなど、待ちを解く */
  cancelWaiting(): void {
    this.waiting = false;
    this.update();
  }

  private bubble(final: boolean): void {
    const text = this.replyText.trim();
    if (text) sendCue({ kind: "bubble", text, final });
  }

  private current(): { state: BaseState; detail?: string } {
    if (this.connectionError) return { state: "error", detail: this.connectionError };
    if (this.audioPlaying || this.streaming) return { state: "speaking" };
    if (this.waiting) return { state: "thinking" };
    if (this.typing) return { state: "listening" };
    return { state: "idle" };
  }

  private update(): void {
    const { state, detail } = this.current();
    if (state === this.lastState && detail === this.lastDetail) return;
    this.lastState = state;
    this.lastDetail = detail;
    const cue: AvatarCue = { kind: "state", state, ...(detail ? { detail } : {}) };
    sendCue(cue);
  }
}
