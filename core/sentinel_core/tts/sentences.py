"""LLM のトークン列を「読み上げる文」に切る(仕様 §18.4 の文単位ストリーミング)。

全文を待たず、最初の文が閉じた時点で合成を始めると、話し始めが早くなる。
"""

from __future__ import annotations

import re

# 文の終わり。閉じかっこ・引用符が続くならそこまで含める(「はい。」→ 」まで)
_END = re.compile(r"[。！？!?\n]+[」』）)\"']*")
# 読まない部分: ト書き(（微笑んで）など)、*強調* の記号、絵文字、Markdown の記号
_STAGE = re.compile(r"[（(][^（）()]*[）)]")
_MARKUP = re.compile(r"[*_`#>|~]+")
_EMOJI = re.compile("[\U0001f000-\U0001faff☀-➿️]")
# 声に出せる文字(かな・漢字・英数字)が1つも無い文は合成しない
_SPEAKABLE = re.compile(r"[\w぀-ヿ一-鿿]")
# 長すぎる文は読点で切る(1文の合成待ちで話し始めが遅れないように)
MAX_CHARS = 80


def clean_for_speech(text: str) -> str:
    text = _STAGE.sub("", text)
    text = _MARKUP.sub("", text)
    text = _EMOJI.sub("", text)
    return " ".join(text.split())


def speakable(text: str) -> bool:
    return bool(_SPEAKABLE.search(text))


class SentenceSplitter:
    """feed() に差分を入れると、閉じた文から順に返す。最後に flush() で残りを返す。"""

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, delta: str) -> list[str]:
        self._buf += delta
        out: list[str] = []
        while True:
            m = _END.search(self._buf)
            if m and m.end() < len(self._buf):
                # 区切りの直後にまだ文字がある = 閉じかっこ等の続きが来ないと確定
                cut = m.end()
            elif len(self._buf) > MAX_CHARS and (i := self._buf.rfind("、", 0, MAX_CHARS)) > 0:
                cut = i + 1
            else:
                break
            out.append(self._buf[:cut])
            self._buf = self._buf[cut:]
        return [s for s in (clean_for_speech(x) for x in out) if speakable(s)]

    def flush(self) -> list[str]:
        rest, self._buf = self._buf, ""
        s = clean_for_speech(rest)
        return [s] if speakable(s) else []
