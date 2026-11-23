"""TTS(音声合成)の差し込み口(仕様 §18、ポート&アダプタ)。

エンジンはこの `TTSEngine` の形さえ満たせば差し替えられる。今は VOICEVOX
(`voicevox.py`)だけ。将来 Style-Bert-VITS2 などを足すときは同じ形のクラスを書き、
`factory.make_engine` に1行足す。

口パクはエンジンに依存させない。エンジンは「音声(WAV)」と、分かるなら
「いつ・どの母音の口か(Viseme の列)」を返すだけ。母音が分からないエンジンは
visemes=None を返し、画面側が文字から推測する(app/src/features/avatar/lipsync.ts)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

# VRM の口の形(5母音)。None は口を閉じる(ん・っ・無音)
Vowel = Literal["aa", "ih", "ou", "ee", "oh"]


class TTSUnavailableError(Exception):
    """エンジンに繋がらない・合成に失敗した。文面はそのまま画面の通知に出す。"""


@dataclass(frozen=True)
class Viseme:
    """口の形1つ分。start/end は音声の先頭からの秒。"""

    vowel: Vowel | None
    start: float
    end: float

    def to_json(self) -> list[object]:
        # 1文に数十個並ぶので、WS で送るときは [母音, 始, 終] の短い形にする
        return [self.vowel, round(self.start, 3), round(self.end, 3)]


@dataclass(frozen=True)
class VoiceParams:
    """どの声で、どう話すか。speaker はエンジンごとの話者(スタイル)ID。"""

    speaker: int | None = None
    speed: float = 1.0  # 話す速さ(1.0 が標準)
    pitch: float = 0.0  # 声の高さ(0 が標準。VOICEVOX は -0.15〜0.15 くらいが目安)
    intonation: float = 1.0  # 抑揚
    volume: float = 1.0


@dataclass(frozen=True)
class Speech:
    """合成結果。wav はファイルにそのまま書ける WAV のバイト列。"""

    wav: bytes
    duration: float
    visemes: list[Viseme] | None = None


@dataclass(frozen=True)
class VoiceStyle:
    id: int
    name: str


@dataclass(frozen=True)
class SpeakerInfo:
    """話者(キャラ)と、その声のスタイル(ノーマル・ささやき 等)。"""

    name: str
    styles: list[VoiceStyle] = field(default_factory=list)
    # 生成音声を公開するときに要るクレジット表記(例: "VOICEVOX:冥鳴ひまり")
    credit: str = ""


class TTSEngine(Protocol):
    """TTS エンジンの差し込み口。"""

    name: str

    async def is_available(self) -> bool: ...

    async def speakers(self) -> list[SpeakerInfo]: ...

    async def synthesize(self, text: str, voice: VoiceParams) -> Speech: ...

    async def aclose(self) -> None: ...
