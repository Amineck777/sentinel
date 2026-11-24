/**
 * コアから届いた音声(audio_chunk)を順番に、すき間なく鳴らす。
 *
 * <audio> を1つずつ鳴らすと文の切れ目で途切れるので、Web Audio API で
 * 「前の文が終わる時刻」に次の文の開始を予約する。鳴り始めの時刻に合わせて
 * アバター窓へ口パクを送る(lipsyncChannel)。
 */
import { sendLipsync, type VisemeTriple } from "./lipsyncChannel";

export type AudioChunk = {
  turn: number;
  seq: number;
  text: string;
  format: "wav";
  data_b64: string;
  duration: number;
  visemes: VisemeTriple[] | null;
  /** この文の表情(コアの expression.py が決める)。古いコアには無い */
  emotion?: string;
};

/** 試聴など、ターンに属さない音声 */
export type Clip = Omit<AudioChunk, "turn" | "seq">;

function decodeBase64(b64: string): ArrayBuffer {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

export class VoicePlayer {
  private ctx: AudioContext | null = null;
  /** 次の文を鳴らし始める時刻(AudioContext の時計、秒) */
  private nextAt = 0;
  /** 今鳴らしているターン。これより古いターンの音声は捨てる */
  private turn = -1;
  /** stop() のたびに増やす。デコード中に止められた音声を鳴らさないための目印 */
  private epoch = 0;
  /** デコードは非同期なので、届いた順に鳴るよう1本の Promise に繋ぐ */
  private chain: Promise<void> = Promise.resolve();
  private sources = new Set<AudioBufferSourceNode>();
  private timers = new Set<number>();
  private playing = false;
  private readonly listeners = new Set<(playing: boolean) => void>();

  constructor() {
    // 自動再生の制限で AudioContext が止まっていたら、最初の操作で動かす
    const resume = () => void this.ctx?.resume();
    window.addEventListener("pointerdown", resume);
    window.addEventListener("keydown", resume);
  }

  /** 返答の音声。新しいターンが来たら前のターンの続きは止める */
  enqueue(chunk: AudioChunk): void {
    if (chunk.turn < this.turn) return;
    if (chunk.turn > this.turn) {
      this.stop();
      this.turn = chunk.turn;
    }
    this.schedule(chunk);
  }

  /** 試聴。鳴っているものを止めてすぐ鳴らす */
  play(clip: Clip): void {
    this.stop();
    this.schedule(clip);
  }

  /** 鳴っている音・予約した音をすべて止め、口を閉じる */
  stop(): void {
    this.epoch++;
    for (const s of this.sources) {
      try {
        s.stop();
      } catch {
        // まだ始まっていない音の stop は環境によって例外になる。止められれば十分
      }
    }
    this.sources.clear();
    for (const t of this.timers) clearTimeout(t);
    this.timers.clear();
    this.nextAt = 0;
    sendLipsync({ kind: "stop" });
    this.setPlaying(false);
  }

  /** 声が鳴り始めた・鳴り終わったときに呼ばれる(アバターの「話し中」の判定に使う)。戻り値で解除 */
  onActivity(cb: (playing: boolean) => void): () => void {
    this.listeners.add(cb);
    return () => {
      this.listeners.delete(cb);
    };
  }

  private setPlaying(on: boolean): void {
    if (this.playing === on) return;
    this.playing = on;
    for (const cb of this.listeners) cb(on);
  }

  private schedule(clip: Clip): void {
    const epoch = this.epoch;
    this.chain = this.chain
      .then(async () => {
        const ctx = (this.ctx ??= new AudioContext());
        if (ctx.state === "suspended") void ctx.resume();
        const buffer = await ctx.decodeAudioData(decodeBase64(clip.data_b64));
        if (epoch !== this.epoch) return; // デコード中に止められた

        const src = ctx.createBufferSource();
        src.buffer = buffer;
        src.connect(ctx.destination);
        const startAt = Math.max(ctx.currentTime + 0.03, this.nextAt);
        src.start(startAt);
        this.nextAt = startAt + buffer.duration;
        this.sources.add(src);
        src.onended = () => {
          this.sources.delete(src);
          if (this.sources.size === 0 && epoch === this.epoch) this.setPlaying(false);
        };

        // 鳴り始めに合わせて口パクを送る
        const timer = window.setTimeout(
          () => {
            this.timers.delete(timer);
            this.setPlaying(true);
            sendLipsync({
              kind: "speak",
              text: clip.text,
              duration: buffer.duration,
              visemes: clip.visemes,
              emotion: clip.emotion ?? null,
            });
          },
          Math.max(0, (startAt - ctx.currentTime) * 1000),
        );
        this.timers.add(timer);
      })
      .catch((e: unknown) => console.warn("[voice] 再生できませんでした", e));
  }
}
