import json
import os
import shutil
import subprocess
import uuid
import wave
from pathlib import Path
from typing import Any

from vosk import KaldiRecognizer, Model

from config import MODELS_DIR, UPLOADS_DIR, VOSK_MODELS


class STTError(Exception):
    pass


_MODEL_CACHE: dict[str, Model] = {}


def _ffmpeg_bin() -> str | None:
    return os.getenv("FFMPEG_PATH") or shutil.which("ffmpeg")


def _model_path(lang: str) -> Path:
    if lang == "ar_linto":
        return MODELS_DIR / VOSK_MODELS["ar_linto"]["folder"]
    if lang.startswith("ar"):
        primary = MODELS_DIR / VOSK_MODELS["ar"]["folder"]
        fallback = MODELS_DIR / VOSK_MODELS["ar_linto"]["folder"]
        return primary if primary.exists() else fallback
    return MODELS_DIR / VOSK_MODELS["fr"]["folder"]


def _installed_langs() -> list[str]:
    langs = []
    if (MODELS_DIR / VOSK_MODELS["fr"]["folder"]).exists():
        langs.append("fr")
    if (MODELS_DIR / VOSK_MODELS["ar"]["folder"]).exists():
        langs.append("ar")
    elif (MODELS_DIR / VOSK_MODELS["ar_linto"]["folder"]).exists():
        langs.append("ar")
    return langs


def available_languages() -> list[dict[str, Any]]:
    langs = [
        {
            "code": "auto",
            "label": "Auto FR/AR",
            "installed": len(_installed_langs()) > 0,
            "folder": "auto",
        }
    ]

    for code in ["fr", "ar", "ar_linto"]:
        info = VOSK_MODELS[code]
        path = MODELS_DIR / info["folder"]
        langs.append(
            {
                "code": code,
                "label": info["label"],
                "installed": path.exists(),
                "folder": info["folder"],
            }
        )
    return langs


def _load_model(lang: str) -> Model:
    path = _model_path(lang)
    if not path.exists():
        raise STTError(
            f"Modèle Vosk introuvable pour '{lang}'. Dossier attendu: {path}. "
            "Lance: python download_models.py"
        )

    cache_key = str(path.resolve())
    if cache_key not in _MODEL_CACHE:
        _MODEL_CACHE[cache_key] = Model(cache_key)
    return _MODEL_CACHE[cache_key]


def _convert_to_wav(input_path: Path, output_path: Path) -> None:
    ffmpeg = _ffmpeg_bin()
    if not ffmpeg:
        raise STTError(
            "ffmpeg n'est pas installé ou introuvable. Installe-le ou ajoute FFMPEG_PATH."
        )

    command = [
        ffmpeg,
        "-y",
        "-i",
        str(input_path),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        str(output_path),
    ]

    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="ignore")[-1200:]
        raise STTError(f"Erreur conversion audio avec ffmpeg: {detail}")


def _transcribe_wav(wav_path: Path, lang: str) -> tuple[str, dict[str, Any]]:
    model = _load_model(lang)

    with wave.open(str(wav_path), "rb") as wf:
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise STTError("Audio WAV invalide. Il doit être mono PCM 16-bit.")

        rec = KaldiRecognizer(model, wf.getframerate())
        rec.SetWords(True)

        partials = []
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            if rec.AcceptWaveform(data):
                partials.append(json.loads(rec.Result()))

        final = json.loads(rec.FinalResult())

    segments = partials + [final]
    words = []
    texts = []

    for segment in segments:
        text = (segment.get("text") or "").strip()
        if text:
            texts.append(text)
        for word in segment.get("result") or []:
            words.append(word)

    text = " ".join(texts).strip()
    conf_values = [float(w.get("conf", 0.0)) for w in words if "conf" in w]
    avg_conf = sum(conf_values) / len(conf_values) if conf_values else 0.0

    return text, {
        "lang": lang,
        "avg_conf": round(avg_conf, 4),
        "word_count": len(words),
        "text_length": len(text),
    }


def _contains_arabic(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06FF" or "\u0750" <= ch <= "\u077F" for ch in text)


def _auto_choose(candidates: list[tuple[str, str, dict[str, Any]]]) -> tuple[str, dict[str, Any]]:
    if not candidates:
        return "", {"lang": "auto", "candidates": []}

    scored = []
    for lang, text, meta in candidates:
        score = float(meta.get("avg_conf", 0.0))
        score += min(len(text), 160) / 1600.0
        score += min(int(meta.get("word_count", 0)), 25) / 500.0

        # Script bonus: Arabic model output usually contains Arabic script.
        if lang.startswith("ar") and _contains_arabic(text):
            score += 0.12
        if lang == "fr" and text and not _contains_arabic(text):
            score += 0.05

        scored.append((score, lang, text, meta))

    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_lang, best_text, best_meta = scored[0]
    return best_text, {
        "lang": best_lang,
        "auto": True,
        "score": round(best_score, 4),
        "candidates": [
            {
                "lang": lang,
                "score": round(score, 4),
                "avg_conf": meta.get("avg_conf"),
                "word_count": meta.get("word_count"),
                "text": text,
            }
            for score, lang, text, meta in scored
        ],
    }


def transcribe_audio(audio_file, lang: str = "auto") -> tuple[str, dict[str, Any]]:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    suffix = Path(audio_file.filename or "audio.webm").suffix or ".webm"
    raw_path = UPLOADS_DIR / f"input_{uuid.uuid4().hex}{suffix}"
    wav_path = UPLOADS_DIR / f"converted_{uuid.uuid4().hex}.wav"

    audio_file.save(raw_path)

    try:
        _convert_to_wav(raw_path, wav_path)

        requested = (lang or "auto").lower().strip()
        if requested in {"", "auto"}:
            installed = _installed_langs()
            if not installed:
                raise STTError("Aucun modèle Vosk installé. Lance: python download_models.py")
            if len(installed) == 1:
                text, meta = _transcribe_wav(wav_path, installed[0])
                meta["auto"] = True
                return text, meta

            candidates = []
            for candidate_lang in installed:
                try:
                    text, meta = _transcribe_wav(wav_path, candidate_lang)
                    candidates.append((candidate_lang, text, meta))
                except Exception as error:
                    candidates.append((candidate_lang, "", {"error": str(error), "avg_conf": 0, "word_count": 0}))
            return _auto_choose(candidates)

        normalized = "ar" if requested.startswith("ar") else "fr"
        return _transcribe_wav(wav_path, normalized)
    finally:
        for path in [raw_path, wav_path]:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
