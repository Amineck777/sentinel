"""VOICEVOX CORE(同梱ライブラリ)のアダプタ。VOICEVOX のアプリを起動しなくても声が出る。

VOICEVOX ENGINE(`voicevox.py`)は「別に起動した VOICEVOX に HTTP で頼む」形だった。
こちらは音声合成の中身(VOICEVOX CORE)を Python ライブラリとしてコアの中で直接動かす。

動かすのに要るもの(どれも git には入れない。`scripts/setup_voicevox_core.py` が
利用者の PC に取ってくる。置き場所の既定は {APP_DATA}/sentinel/voicevox_core/):
  - Python パッケージ `voicevox_core`(PyPI に無いので、GitHub の wheel を pip で入れる)
  - onnxruntime/  … 推論ランタイム(VOICEVOX 版 ONNX Runtime の DLL)
  - dict/         … Open JTalk の辞書(漢字の読み・アクセントを決める)
  - models/vvms/  … 音声モデル(.vvm)。エヴァの声 暁記ミタマ(122〜125)は 24.vvm

GPU(VRAM)は LLM(Gemma 4 E4B)が使うので、ここでは必ず CPU で合成する(ADR 0115)。

重い処理を起動時に一度に済ませないための工夫:
  - パッケージの import とファイルの準備は、最初に使われたときに行う(遅延初期化)
  - .vvm は「開く」だけなら中のメタ情報(話者名・スタイルID)を読むだけで軽い。
    実際にモデルを読み込む(数秒・数百MB)のは、そのスタイルで初めて話すとき
  - 既定の声(config の speaker_id)だけは、準備ができた直後に裏で読み込み始め、
    最初の返事で待たされないようにする
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import importlib
import time
from pathlib import Path
from typing import Any

from sentinel_core.tts.base import SpeakerInfo, Speech, TTSUnavailableError, VoiceParams, VoiceStyle
from sentinel_core.tts.voicevox import visemes_from_query, wav_duration

SETUP_HINT = "core\\.venv\\Scripts\\python.exe scripts\\setup_voicevox_core.py を実行してください"

# 話す声ではないスタイル(歌声など)。話者一覧と合成の対象から外す
_NON_TALK_TYPES = {"singing_teacher", "frame_decode", "sing"}

# 準備に失敗したあと、次に試し直すまでの秒数(設定画面が状態を何度も聞いてくるため、
# 毎回 DLL の読み込みを試して遅くならないように間を空ける)
_RETRY_AFTER_SEC = 10.0


def query_to_engine_dict(query: Any) -> dict[str, Any]:
    """CORE の AudioQuery(Python のデータクラス)を、ENGINE の JSON と同じ形の dict にする。

    口パクの変換(`visemes_from_query`)は ENGINE の JSON(キャメルケース)を読む。
    同じ関数を使い回すため、必要な項目だけを詰め替える(口パクの作り方を1か所に保つ)。
    """

    def mora(m: Any) -> dict[str, Any]:
        return {
            "vowel": m.vowel,
            "vowel_length": m.vowel_length,
            "consonant_length": m.consonant_length,
        }

    return {
        "speedScale": query.speed_scale,
        "prePhonemeLength": query.pre_phoneme_length,
        "accent_phrases": [
            {
                "moras": [mora(m) for m in ap.moras],
                "pause_mora": mora(ap.pause_mora) if ap.pause_mora is not None else None,
            }
            for ap in query.accent_phrases
        ],
    }


def _find_first(root: Path, patterns: list[str]) -> Path | None:
    """root の下から、patterns の順に最初に見つかったものを返す(版の違いで名前が変わるため)。"""
    for pat in patterns:
        hits = sorted(root.glob(pat))
        if hits:
            return hits[0]
    return None


class VoicevoxCoreEngine:
    name = "voicevox_core"

    def __init__(
        self,
        base_dir: Path,
        cpu_threads: int = 0,
        preload_style: int | None = None,
        module: Any | None = None,  # テストで偽の voicevox_core を渡す
    ) -> None:
        self._dir = base_dir
        self._cpu_threads = cpu_threads
        self._preload_style = preload_style
        self._module = module  # import した voicevox_core(遅延で入る)
        self._synth: Any = None
        # スタイルID → そのスタイルが入っている .vvm(開いたまま持つ。読み込みに使うため)
        self._style_model: dict[int, Any] = {}
        self._models: list[Any] = []
        self._loaded: set[Any] = set()  # 読み込み済みのモデルID
        self._init_lock = asyncio.Lock()
        self._load_lock = asyncio.Lock()
        self._error: str | None = None
        self._error_at = 0.0
        self._preload_task: asyncio.Task[None] | None = None

    # --- 準備(遅延初期化)---

    async def _ensure(self) -> None:
        """初回だけ: import → ONNX Runtime → 辞書 → .vvm を開く。失敗は文面にして投げる。"""
        if self._synth is not None:
            return
        async with self._init_lock:
            if self._synth is not None:
                return
            if self._error and time.monotonic() - self._error_at < _RETRY_AFTER_SEC:
                raise TTSUnavailableError(self._error)
            try:
                await self._setup()
            except TTSUnavailableError as e:
                self._error, self._error_at = str(e), time.monotonic()
                raise
            except Exception as e:  # DLL の不一致など。原因の文面ごと画面に出す
                self._error = f"VOICEVOX CORE の準備に失敗しました: {e}"
                self._error_at = time.monotonic()
                raise TTSUnavailableError(self._error) from e
            self._error = None
            if self._preload_style is not None and self._preload_style in self._style_model:
                # 既定の声は裏で読み込み始める(ここで待つと設定画面の表示が数秒止まるため)
                self._preload_task = asyncio.get_running_loop().create_task(
                    self._preload(self._preload_style)
                )

    async def _setup(self) -> None:
        if self._module is None:
            try:
                self._module = importlib.import_module("voicevox_core")
            except ImportError as e:
                raise TTSUnavailableError(
                    f"VOICEVOX CORE(Python パッケージ)が入っていません。{SETUP_HINT}。"
                ) from e
        vv = importlib.import_module(f"{self._module.__name__}.asyncio")

        if not self._dir.is_dir():
            raise TTSUnavailableError(
                f"VOICEVOX CORE のファイルが見つかりません({self._dir})。{SETUP_HINT}。"
            )
        ort_name = vv.Onnxruntime.LIB_RECOMMENDED_VERSIONED_FILENAME
        # ダウンローダーは onnxruntime/lib/ に置く。版によって置き方が違っても拾えるよう探す
        ort_path = _find_first(
            self._dir, [f"onnxruntime/lib/{ort_name}", f"onnxruntime/**/{ort_name}"]
        )
        dict_dir = _find_first(
            self._dir, ["dict/open_jtalk_dic_utf_8-*", "**/open_jtalk_dic_utf_8-*"]
        )
        vvms = sorted((self._dir / "models").glob("**/*.vvm"))
        missing = [
            label
            for label, ok in (("ONNX Runtime", ort_path), ("辞書", dict_dir), ("音声モデル", vvms))
            if not ok
        ]
        if missing:
            raise TTSUnavailableError(
                f"VOICEVOX CORE の{'・'.join(missing)}が見つかりません({self._dir})。{SETUP_HINT}。"
            )

        ort = await vv.Onnxruntime.load_once(filename=str(ort_path))
        ojt = await vv.OpenJtalk.new(str(dict_dir))
        # CPU 固定: GPU は LLM に譲る。cpu_num_threads=0 は「CORE に任せる」
        synth = vv.Synthesizer(ort, ojt, acceleration_mode="CPU", cpu_num_threads=self._cpu_threads)

        for path in vvms:
            model = await vv.VoiceModelFile.open(str(path))
            self._models.append(model)
            for character in model.metas:
                for style in character.styles:
                    if getattr(style, "type", "talk") not in _NON_TALK_TYPES:
                        self._style_model.setdefault(int(style.id), model)
        self._synth = synth

    async def _preload(self, style: int) -> None:
        # 失敗しても、話すときにもう一度試して通知が出るので、ここでは握りつぶす
        with contextlib.suppress(Exception):
            await self._load_for(style)

    async def _load_for(self, style: int) -> None:
        """そのスタイルの入った .vvm がまだ読み込まれていなければ読み込む。"""
        model = self._style_model.get(style)
        if model is None:
            raise TTSUnavailableError(
                f"声(スタイルID {style})の音声モデルが入っていません。"
                "設定の「声」で別の声を選ぶか、セットアップで音声モデルを追加してください。"
            )
        async with self._load_lock:  # 同じモデルを2回読まないよう、読み込みは1つずつ
            if model.id in self._loaded:
                return
            await self._synth.load_voice_model(model)
            self._loaded.add(model.id)

    # --- TTSEngine の形 ---

    async def is_available(self) -> bool:
        try:
            await self._ensure()
        except TTSUnavailableError:
            return False
        return True

    async def speakers(self) -> list[SpeakerInfo]:
        await self._ensure()
        # 同じ話者が複数の .vvm に分かれていることがある(例: ささやき声だけ別ファイル)。
        # 名前でまとめて1人の話者として出す
        by_name: dict[str, list[VoiceStyle]] = {}
        seen: set[int] = set()
        for model in self._models:
            for character in model.metas:
                for st in character.styles:
                    sid = int(st.id)
                    if getattr(st, "type", "talk") in _NON_TALK_TYPES or sid in seen:
                        continue
                    seen.add(sid)
                    by_name.setdefault(str(character.name), []).append(
                        VoiceStyle(id=sid, name=str(st.name))
                    )
        return [
            SpeakerInfo(name=n, styles=styles, credit=f"VOICEVOX:{n}")
            for n, styles in by_name.items()
        ]

    async def synthesize(self, text: str, voice: VoiceParams) -> Speech:
        await self._ensure()
        style = voice.speaker if voice.speaker is not None else min(self._style_model, default=-1)
        await self._load_for(style)
        try:
            query = await self._synth.create_audio_query(text, style)
            # 話す速さ・高さなどは音声クエリに書き込んでから合成する(ENGINE と同じやり方)
            query = dataclasses.replace(
                query,
                speed_scale=voice.speed,
                pitch_scale=voice.pitch,
                intonation_scale=voice.intonation,
                volume_scale=voice.volume,
            )
            wav: bytes = await self._synth.synthesis(query, style)
        except Exception as e:
            raise TTSUnavailableError(f"VOICEVOX CORE の合成に失敗しました: {e}") from e
        return Speech(
            wav=wav,
            duration=wav_duration(wav),
            visemes=visemes_from_query(query_to_engine_dict(query)),
        )

    async def aclose(self) -> None:
        if self._preload_task:
            self._preload_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._preload_task
        for model in self._models:
            with contextlib.suppress(Exception):
                await model.close()
        if self._synth is not None:
            with contextlib.suppress(Exception):
                await self._synth.close()
