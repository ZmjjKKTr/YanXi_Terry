"""
语音识别模块 — 离线 Vosk（默认）/ 可扩展 Whisper
"""
import json
from pathlib import Path

from config import ASR_ENGINE, VOSK_MODEL_PATH

_vosk_model = None


def _get_vosk_model():
    global _vosk_model
    if _vosk_model is None:
        import vosk
        model_path = str(VOSK_MODEL_PATH)
        if not Path(model_path).exists():
            raise FileNotFoundError(
                f"Vosk 模型未找到: {model_path}\n"
                "首次使用请下载: https://alphacephei.com/vosk/models/vosk-model-cn-0.22.zip"
            )
        _vosk_model = vosk.Model(model_path)
    return _vosk_model


def recognize_from_file(audio_path: str, sample_rate: int = 16000) -> str:
    if ASR_ENGINE == "whisper":
        return _recognize_whisper_file(audio_path)
    return _recognize_vosk_file(audio_path, sample_rate)


def recognize_from_mic(duration: float = 10, sample_rate: int = 16000) -> str:
    import sounddevice as sd

    print(f"[REC] 录音 {duration} 秒，请说话...")
    audio = sd.rec(
        int(duration * sample_rate),
        samplerate=sample_rate, channels=1, dtype='int16',
    )
    sd.wait()
    print("处理中...")

    model = _get_vosk_model()
    rec = model.KaldiRecognizer(model, sample_rate)
    audio_bytes = audio.tobytes()

    if rec.AcceptWaveform(audio_bytes):
        result = json.loads(rec.Result())
        text = result.get('text', '')
    else:
        final = json.loads(rec.FinalResult())
        text = final.get('text', '')
        if not text:
            partial = json.loads(rec.PartialResult())
            text = partial.get('partial', '')

    print(f"[OK] 识别结果: {text}" if text else "[FAIL] 未识别到有效语音")
    return text


def _recognize_vosk_file(audio_path: str, sample_rate: int) -> str:
    import wave
    model = _get_vosk_model()
    rec = model.KaldiRecognizer(model, sample_rate)
    rec.SetWords(True)

    with wave.open(audio_path, "rb") as wf:
        if wf.getframerate() != sample_rate:
            raise ValueError(f"音频采样率需为 {sample_rate}Hz，当前: {wf.getframerate()}")
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            rec.AcceptWaveform(data)

    final = json.loads(rec.FinalResult())
    return final.get('text', '')


def _recognize_whisper_file(audio_path: str) -> str:
    import whisper
    model = whisper.load_model("base")
    result = model.transcribe(audio_path, language="zh")
    return result["text"].strip()
