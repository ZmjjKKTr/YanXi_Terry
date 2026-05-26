"""
语音合成模块 — Edge TTS（免费、自然、离线无需 API Key）
"""
import asyncio
import os
import subprocess
import sys
from pathlib import Path

from config import TTS_VOICE, TTS_OUTPUT


async def _synthesize(text: str, output_path: str, voice: str) -> None:
    import edge_tts
    communicate = edge_tts.Communicate(text, voice=voice)
    await communicate.save(output_path)


def synthesize(text: str, output_path: str | None = None, play: bool = True) -> str:
    path = str(output_path) if output_path else str(TTS_OUTPUT)
    voice = TTS_VOICE

    try:
        asyncio.run(_synthesize(text, path, voice))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_synthesize(text, path, voice))

    print(f"[TTS] 语音已生成: {path}")

    if play:
        _play(path)

    return path


def _play(file_path: str) -> None:
    path = Path(file_path)
    if not path.exists():
        print(f"[WARN] 音频文件不存在: {file_path}")
        return
    try:
        if sys.platform == "win32":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.run(["afplay", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception as e:
        print(f"[WARN] 播放失败: {e}")
