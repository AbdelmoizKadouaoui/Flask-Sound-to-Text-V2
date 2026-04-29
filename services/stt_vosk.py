import json
import shutil
import subprocess
import uuid
import wave
from pathlib import Path
from typing import Dict, Tuple

from vosk import KaldiRecognizer, Model, SetLogLevel

from config import GENERATED_DIR, UPLOAD_DIR, VOSK_MODELS

SetLogLevel(-1)

_MODEL_CACHE: Dict[str, Model] = {}


class STTError(RuntimeError):
    pass


def available_languages() -> Dict[str, dict]:
    return {
        key: {
            "label": item["label"],
            "installed": Path(item["path"]).exists(),
            "path": str(item["path"]),
        }
        for key, item in VOSK_MODELS.items()
    }


def _ensure_dirs() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)


def _require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise STTError(
            "ffmpeg n'est pas trouvé par Flask. Ouvre /api/debug/ffmpeg pour vérifier. "
            "Windows: winget install Gyan.FFmpeg puis ferme/réouvre PowerShell/VS Code."
        )


def _load_model(lang: str) -> Model:
    if lang not in VOSK_MODELS:
        raise STTError(f"Langue non supportée: {lang}")

    model_path = Path(VOSK_MODELS[lang]["path"])
    if not model_path.exists():
        raise STTError(
            f"Modèle Vosk introuvable pour '{lang}'. Chemin attendu: {model_path}. "
            "Lance: python download_models.py"
        )

    if lang not in _MODEL_CACHE:
        _MODEL_CACHE[lang] = Model(str(model_path))
    return _MODEL_CACHE[lang]


def _convert_to_wav_16k_mono(input_path: Path, output_path: Path) -> None:
    _require_ffmpeg()
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-ar",
        "16000",
        "-ac",
        "1",
        "-f",
        "wav",
        str(output_path),
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise STTError("Conversion audio échouée avec ffmpeg: " + result.stderr[-1000:])


def transcribe_audio(file_storage, lang: str) -> Tuple[str, dict]:
    """Receive a Flask FileStorage, convert browser audio to 16k PCM WAV, run Vosk."""
    _ensure_dirs()

    ext = Path(file_storage.filename or "audio.webm").suffix or ".webm"
    raw_path = UPLOAD_DIR / f"recording_{uuid.uuid4().hex}{ext}"
    wav_path = UPLOAD_DIR / f"recording_{uuid.uuid4().hex}.wav"

    try:
        file_storage.save(raw_path)

        if not raw_path.exists() or raw_path.stat().st_size == 0:
            raise STTError("Fichier audio vide reçu par Flask.")

        _convert_to_wav_16k_mono(raw_path, wav_path)

        model = _load_model(lang)
        recognizer = KaldiRecognizer(model, 16000)
        recognizer.SetWords(True)

        final_text_parts = []
        partial_meta = []
        frames_read = 0

        with wave.open(str(wav_path), "rb") as wf:
            if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != 16000:
                raise STTError("Le WAV converti doit être mono PCM 16kHz 16-bit.")

            while True:
                data = wf.readframes(4000)
                if not data:
                    break
                frames_read += len(data)
                if recognizer.AcceptWaveform(data):
                    result = json.loads(recognizer.Result())
                    text = result.get("text", "").strip()
                    if text:
                        final_text_parts.append(text)
                    partial_meta.append(result)

        final_result = json.loads(recognizer.FinalResult())
        final_text = final_result.get("text", "").strip()
        if final_text:
            final_text_parts.append(final_text)
        partial_meta.append(final_result)

        text = " ".join(final_text_parts).strip()
        return text, {"segments": partial_meta, "frames_read": frames_read, "lang": lang}
    finally:
        for path in (raw_path, wav_path):
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass
