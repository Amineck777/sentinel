// 口パク(リップシンク)の純粋ロジック。three.js に依存しないので単体で確かめやすい。
//
// VRM の口の形は 5 母音(aa / ih / ou / ee / oh)の表情で表す。
// ここでは「文字列 → 母音の列 → 時刻つきの並び(タイムライン)」に変換し、
// 毎フレーム「いま何の口か」を引く。TTS(VOICEVOX など)が母音と長さを返すときは
// fromTriples でそれをそのまま使い、返さないエンジンでは fitText で文字から推測する(学習ノート 06)。

export type Vowel = "aa" | "ih" | "ou" | "ee" | "oh";
/** null は口を閉じる(ん・っ・句読点・空白) */
export type Viseme = Vowel | null;

export const VOWELS: readonly Vowel[] = ["aa", "ih", "ou", "ee", "oh"];

const ROWS: Record<Vowel, string> = {
  aa: "あかさたなはまやらわがざだばぱぁゃゎ",
  ih: "いきしちにひみりぎじぢびぴぃ",
  ou: "うくすつぬふむゆるぐずづぶぷぅゅゔ",
  ee: "えけせてねへめれげぜでべぺぇ",
  oh: "おこそとのほもよろをごぞどぼぽぉょ",
};

const KANA_TO_VOWEL = new Map<string, Vowel>();
for (const v of VOWELS) for (const ch of ROWS[v]) KANA_TO_VOWEL.set(ch, v);

/** 直前の文字と合わさって1拍になる小さい文字(きゃ・ふぁ など) */
const SMALL = new Set("ぁぃぅぇぉゃゅょゎ");
const CLOSED = new Set("んっ");
const LATIN: Record<string, Vowel> = { a: "aa", i: "ih", u: "ou", e: "ee", o: "oh" };
/** 読みが分からない文字(漢字など)に当てる仮の口。単調にならないよう順に回す */
const FALLBACK_CYCLE: readonly Vowel[] = ["aa", "oh", "ih", "ee", "ou"];

function toHiragana(ch: string): string {
  const code = ch.charCodeAt(0);
  // カタカナ(ァ U+30A1 〜 ヶ U+30F6)はひらがなと 0x60 ずれているだけ
  if (code >= 0x30a1 && code <= 0x30f6) return String.fromCharCode(code - 0x60);
  return ch;
}

/**
 * 文字列を1拍(モーラ)ごとの口の形に変える。
 * 漢字は読みが分からないので1文字=2拍として仮の母音を当てる(見た目が動けば十分な段階A用)。
 */
export function textToVisemes(text: string): Viseme[] {
  const out: Viseme[] = [];
  let fallback = 0;
  for (const raw of text) {
    const ch = toHiragana(raw);
    const lower = ch.toLowerCase();
    if (SMALL.has(ch) && out.length > 0 && out[out.length - 1] !== null) {
      out[out.length - 1] = KANA_TO_VOWEL.get(ch) ?? out[out.length - 1];
    } else if (KANA_TO_VOWEL.has(ch)) {
      out.push(KANA_TO_VOWEL.get(ch)!);
    } else if (ch === "ー") {
      out.push(out.length > 0 ? out[out.length - 1] : null);
    } else if (CLOSED.has(ch)) {
      out.push(null);
    } else if (lower in LATIN) {
      out.push(LATIN[lower]);
    } else if (/[\p{Script=Han}]/u.test(ch)) {
      out.push(FALLBACK_CYCLE[fallback++ % FALLBACK_CYCLE.length]);
      out.push(FALLBACK_CYCLE[fallback++ % FALLBACK_CYCLE.length]);
    } else if (/[、。,.!?！？…\s]/u.test(ch)) {
      // 句読点は少し長めに口を閉じる
      out.push(null, null);
    }
    // それ以外(英子音・記号)は口の形を変えない
  }
  return out;
}

export interface Segment {
  viseme: Viseme;
  start: number;
  end: number;
}

/** 1拍の長さ(秒)を掛けて時刻つきの並びにする。日本語の話し言葉は 1拍 ≒ 0.12〜0.15 秒 */
export function buildTimeline(visemes: Viseme[], moraSec = 0.13): Segment[] {
  return visemes.map((viseme, i) => ({ viseme, start: i * moraSec, end: (i + 1) * moraSec }));
}

export function timelineDuration(timeline: Segment[]): number {
  return timeline.length > 0 ? timeline[timeline.length - 1].end : 0;
}

/**
 * 時刻 t の母音ごとの重み(0〜1)を返す。
 * 拍の真ん中で最大、端で小さくする(三角形)ことで、拍の切れ目で口がパタパタしすぎない。
 */
export function sampleTimeline(timeline: Segment[], t: number): Record<Vowel, number> {
  const w: Record<Vowel, number> = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };
  const seg = timeline.find((s) => t >= s.start && t < s.end);
  if (!seg || seg.viseme === null) return w;
  const p = (t - seg.start) / (seg.end - seg.start);
  w[seg.viseme] = 0.35 + 0.65 * Math.sin(Math.PI * p);
  return w;
}

/** TTS が返したタイムライン([母音, 開始秒, 終了秒] の列)を Segment にする */
export function fromTriples(triples: [Viseme, number, number][]): Segment[] {
  return triples.map(([viseme, start, end]) => ({ viseme, start, end }));
}

/**
 * 母音が分からない TTS 用: 文字から口の並びを推測し、音声の長さ(秒)にちょうど収める。
 * 漢字の読みは分からないので精度は粗いが、話し始めと終わりは音声とそろう。
 */
export function fitText(text: string, duration: number): Segment[] {
  const visemes = textToVisemes(text);
  if (visemes.length === 0 || duration <= 0) return [];
  return buildTimeline(visemes, duration / visemes.length);
}
