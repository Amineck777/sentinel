"""返答の感情(アバターの表情)を決める。

アバターの表情は 2 つの手がかりから決める(学習ノート 07):

1. 感情タグ: モデルが `[joy]` のように書いたら、それに従う。タグは画面にも声にも出さず、
   ここで取り除く。次のタグが来るまで同じ感情を保つ
2. 言葉からの推測: タグが無いモデル(今のエヴァなど)でも表情が動くよう、文ごとに
   「嬉しい」「申し訳」などの言葉から控えめに推測する。見つからなければ neutral

どちらも「文」(tts/sentences.py と同じ切り方)の単位で決めるので、声の文と表情の切り替えがそろう。
"""

from __future__ import annotations

from sentinel_core.tts.sentences import SentenceSplitter

# 画面(アバター)とやりとりする感情の名前。VRM の表情への対応はアバター側が持つ
EMOTIONS = ("neutral", "joy", "fun", "sorrow", "angry", "surprised")
_ALIASES = {
    "happy": "joy",
    "relaxed": "fun",
    "sad": "sorrow",
    "surprise": "surprised",
    "anger": "angry",
    "calm": "neutral",
}
# タグの開き・閉じ(全角も受ける)。これより長い [...] はタグではない(Markdown のリンクなど)
_OPEN = "[［"
_CLOSE = "]］"
MAX_TAG = 12

# 言葉から推測するときの手がかり。落ち着いたメイドの口調で出やすいものだけ、控えめに
_CUES: dict[str, tuple[str, ...]] = {
    "sorrow": ("申し訳", "残念", "寂し", "さみし", "悲し", "心配", "ごめんなさい", "つらい"),
    "joy": ("嬉し", "うれし", "よかった", "良かった", "ありがと", "おめでと", "何より", "素敵"),
    "surprised": ("まあ", "えっ", "驚", "びっくり", "まさか"),
    "angry": ("いけません", "だめです", "ダメです", "許しません"),
    "fun": ("楽し", "面白", "おもしろ", "ふふ"),
}


def normalize(name: str) -> str | None:
    """タグの中身を感情の名前にする。知らない名前なら None(タグとして扱わない)。"""
    key = name.strip().lower()
    key = _ALIASES.get(key, key)
    return key if key in EMOTIONS else None


def guess_emotion(sentence: str) -> str:
    """文の言葉から感情を推測する。いちばん先に出てきた手がかりを採る。"""
    best: tuple[int, str] | None = None
    for emotion, cues in _CUES.items():
        for cue in cues:
            i = sentence.find(cue)
            if i >= 0 and (best is None or i < best[0]):
                best = (i, emotion)
    return best[1] if best else "neutral"


class TagFilter:
    """トークンの流れから感情タグを抜き出す。タグがトークンの境目で割れても扱える。"""

    def __init__(self) -> None:
        self._pending = ""

    def feed(self, delta: str) -> list[str | Tag]:
        """文字列とタグを出てきた順に返す。閉じていないタグの候補は次回へ持ち越す。"""
        text, self._pending = self._pending + delta, ""
        items: list[str | Tag] = []
        buf: list[str] = []
        i = 0
        while i < len(text):
            ch = text[i]
            if ch not in _OPEN:
                buf.append(ch)
                i += 1
                continue
            close = next((j for j in range(i + 1, len(text)) if text[j] in _CLOSE), -1)
            if close < 0:
                if len(text) - i <= MAX_TAG:
                    self._pending = text[i:]  # まだ閉じていない。続きを待つ
                    break
                buf.append(ch)
                i += 1
                continue
            emotion = normalize(text[i + 1 : close]) if close - i <= MAX_TAG else None
            if emotion is None:
                buf.append(ch)
                i += 1
                continue
            if buf:
                items.append("".join(buf))
                buf = []
            items.append(Tag(emotion))
            i = close + 1
            if i < len(text) and text[i] == " ":
                i += 1  # 「[joy] はい」の空白も一緒に消す
        if buf:
            items.append("".join(buf))
        return items

    def flush(self) -> str:
        rest, self._pending = self._pending, ""
        return rest


class Tag(str):
    """TagFilter が返す「感情タグ」。ただの文字列と区別するための印"""


class TurnExpression:
    """1ターン分。トークンを受け取り、画面に出す文字と「閉じた文とその感情」を返す。"""

    def __init__(self) -> None:
        self._tags = TagFilter()
        self._splitter = SentenceSplitter()
        self._explicit: str | None = None

    def feed(self, delta: str) -> tuple[str, list[tuple[str, str]]]:
        clean: list[str] = []
        done: list[tuple[str, str]] = []
        for item in self._tags.feed(delta):
            if isinstance(item, Tag):
                # 前の文が句点まで来ていたら、それは前の感情のまま閉じる
                done += self._label(self._splitter.close_finished())
                self._explicit = str(item)
            else:
                clean.append(item)
                done += self._label(self._splitter.feed(item))
        return "".join(clean), done

    def flush(self) -> tuple[str, list[tuple[str, str]]]:
        """ターンの終わり。持ち越していた文字(閉じなかった [ など)と残りの文を返す。"""
        rest = self._tags.flush()
        sentences = self._splitter.feed(rest) + self._splitter.flush()
        return rest, self._label(sentences)

    def _label(self, sentences: list[str]) -> list[tuple[str, str]]:
        return [(s, self._explicit or guess_emotion(s)) for s in sentences]
