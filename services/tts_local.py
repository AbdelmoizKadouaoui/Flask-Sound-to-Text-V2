import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
import wave
from pathlib import Path
from typing import Any

from config import GENERATED_DIR, PIPER_VOICES, PIPER_VOICES_DIR


class TTSError(Exception):
    pass


_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
_LATIN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿœŒæÆçÇ]")
_LETTER_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿœŒæÆçÇ\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?؟؛;:\n])\s+")
_MULTI_SPACE_RE = re.compile(r"\s+")
_REPEAT_PUNCT_RE = re.compile(r"([,;:!?؟.])\1+")
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.\w+\b")
_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_UNSAFE_SYMBOLS_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]|[<>#*_={}\[\]\\|~^]")

# Piper model cache: loading the ONNX voice for every chunk is the main reason
# long texts feel like one huge slow generation. We load each voice once, then reuse it.
_VOICE_CACHE: dict[str, Any] = {}
_VOICE_LOAD_LOCK = threading.RLock()
_VOICE_SYNTH_LOCKS: dict[str, threading.RLock] = {
    "fr": threading.RLock(),
    "ar": threading.RLock(),
}


def detect_text_language(text: str) -> str:
    if not text:
        return "fr"
    arabic_count = len(_ARABIC_RE.findall(text))
    visible_count = sum(1 for ch in text if not ch.isspace()) or 1
    return "ar" if arabic_count / visible_count >= 0.18 else "fr"


def normalize_tts_lang(lang: str | None, text: str) -> str:
    requested = (lang or "auto").lower().strip()
    if requested in {"", "auto", "detect"}:
        return detect_text_language(text)
    return "ar" if requested.startswith("ar") else "fr"


def _spell_acronyms_for_french(match: re.Match[str]) -> str:
    return " ".join(match.group(0))


def prepare_text_for_tts(text: str, lang: str = "auto") -> str:
    """Clean only things that commonly make Piper produce noise, without over-filtering normal words."""
    text = (text or "").strip()
    if not text:
        return ""

    text = _CODE_BLOCK_RE.sub(" ", text)
    text = _INLINE_CODE_RE.sub(r" \1 ", text)
    text = _URL_RE.sub(" lien web ", text)
    text = _EMAIL_RE.sub(" adresse email ", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("…", ". ").replace("•", ", ")
    text = text.replace("—", " - ").replace("–", " - ")
    text = _UNSAFE_SYMBOLS_RE.sub(" ", text)
    text = _REPEAT_PUNCT_RE.sub(r"\1", text)
    text = re.sub(r"\s*\n\s*", ". ", text)
    text = re.sub(r"([,;:!?؟.])(?=[^\s])", r"\1 ", text)
    text = _MULTI_SPACE_RE.sub(" ", text).strip()

    resolved_lang = normalize_tts_lang(lang, text)

    if resolved_lang == "fr":
        replacements = {
            "&": " et ",
            "@": " arobase ",
            "%": " pour cent ",
            "/": " slash ",
            "+": " plus ",
            "=": " égale ",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        text = re.sub(r"\b[A-Z]{2,8}\b", _spell_acronyms_for_french, text)
        text = re.sub(r"\b[aeiouyAEIOUY]{4,}\b", " ", text)
    else:
        replacements = {
            "&": " و ",
            "%": " بالمئة ",
            "+": " زائد ",
            "=": " يساوي ",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)

    text = _MULTI_SPACE_RE.sub(" ", text).strip()
    return text


def _token_language(token: str) -> str:
    ar = len(_ARABIC_RE.findall(token))
    la = len(_LATIN_RE.findall(token))
    if ar == 0 and la == 0:
        return "neutral"
    return "ar" if ar > la else "fr"


def _split_mixed_language(text: str) -> list[dict[str, str]]:
    tokens = text.split()
    if not tokens:
        return []

    units: list[dict[str, str]] = []
    current_lang: str | None = None
    current_tokens: list[str] = []

    for token in tokens:
        lang = _token_language(token)
        if lang == "neutral":
            lang = current_lang or detect_text_language(token)

        if current_lang is None:
            current_lang = lang
            current_tokens.append(token)
            continue

        if lang == current_lang or _token_language(token) == "neutral":
            current_tokens.append(token)
        else:
            if current_tokens:
                units.append({"text": " ".join(current_tokens), "lang": current_lang})
            current_lang = lang
            current_tokens = [token]

    if current_tokens:
        units.append({"text": " ".join(current_tokens), "lang": current_lang or "fr"})

    return units


def _is_safe_chunk(text: str, lang: str) -> bool:
    chunk = (text or "").strip()
    if len(chunk) < 2:
        return False

    letters = len(_LETTER_RE.findall(chunk))
    if letters == 0:
        return False

    visible = sum(1 for ch in chunk if not ch.isspace()) or 1
    if letters / visible < 0.25:
        return False

    ar = len(_ARABIC_RE.findall(chunk))
    la = len(_LATIN_RE.findall(chunk))
    if lang == "fr" and ar > la and ar >= 3:
        return False
    if lang == "ar" and la > ar and la >= 3:
        return False

    for token in chunk.split():
        if len(token) > 40 and not token.isdigit():
            return False

    if re.search(r"\b([A-Za-zÀ-ÖØ-öø-ÿ])\1{4,}\b", chunk):
        return False

    return True


def split_text_into_tts_units(text: str, lang: str = "auto", max_chars: int | None = None) -> list[dict[str, str]]:
    prepared = prepare_text_for_tts(text, lang)
    if not prepared:
        return []

    requested_lang = (lang or "auto").lower().strip()
    default_lang = normalize_tts_lang(lang, prepared)
    default_limit = max_chars or (180 if default_lang == "fr" else 160)

    sentences = _SENTENCE_SPLIT_RE.split(prepared)
    rough_units: list[dict[str, str]] = []

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        language_units = _split_mixed_language(sentence) if requested_lang in {"", "auto", "detect"} else [
            {"text": sentence, "lang": default_lang}
        ]

        for unit in language_units:
            unit_text = unit["text"].strip()
            unit_lang = normalize_tts_lang(unit.get("lang"), unit_text)
            limit = int(max_chars or default_limit)

            if len(unit_text) <= limit:
                rough_units.append({"text": unit_text, "lang": unit_lang})
                continue

            current = ""
            for word in unit_text.split():
                candidate = f"{current} {word}".strip()
                if len(candidate) <= limit:
                    current = candidate
                else:
                    if current:
                        rough_units.append({"text": current, "lang": unit_lang})
                    current = word
            if current:
                rough_units.append({"text": current, "lang": unit_lang})

    safe_units: list[dict[str, str]] = []
    for unit in rough_units:
        clean = prepare_text_for_tts(unit["text"], unit["lang"])
        unit_lang = normalize_tts_lang(unit["lang"], clean)
        if _is_safe_chunk(clean, unit_lang):
            safe_units.append({"text": clean, "lang": unit_lang})

    # Merge very small adjacent chunks with the same language. This reduces gaps
    # while still keeping the first audio chunk reasonably short.
    merged: list[dict[str, str]] = []
    for unit in safe_units:
        if not merged:
            merged.append(unit)
            continue
        previous = merged[-1]
        limit = int(max_chars or (190 if unit["lang"] == "fr" else 170))
        candidate = f"{previous['text']} {unit['text']}".strip()
        if previous["lang"] == unit["lang"] and len(candidate) <= limit:
            previous["text"] = candidate
        else:
            merged.append(unit)

    return merged


def split_text_into_chunks(text: str, lang: str = "auto", max_chars: int | None = None) -> list[str]:
    return [unit["text"] for unit in split_text_into_tts_units(text, lang, max_chars)]


def _voice_paths(lang: str) -> tuple[Path, Path]:
    info = PIPER_VOICES[lang]
    return PIPER_VOICES_DIR / info["model"], PIPER_VOICES_DIR / info["config"]


def _piper_binary() -> str | None:
    env = os.getenv("PIPER_EXE")
    if env and Path(env).exists():
        return env
    return shutil.which("piper") or shutil.which("piper.exe")


def _piper_installed_as_module() -> bool:
    try:
        import piper  # noqa: F401
        return True
    except Exception:
        return False


def _get_piper_voice(lang: str) -> Any | None:
    try:
        from piper.voice import PiperVoice  # type: ignore
    except Exception:
        return None

    model_path, config_path = _voice_paths(lang)
    if not model_path.exists() or not config_path.exists():
        raise TTSError(
            f"Voix Piper '{lang}' introuvable. Modèle attendu: {model_path}. "
            "Lance: python download_piper_voices.py"
        )

    # Fast path: do not wait for another language loading if this one is already cached.
    if lang in _VOICE_CACHE:
        return _VOICE_CACHE[lang]

    with _VOICE_LOAD_LOCK:
        if lang in _VOICE_CACHE:
            return _VOICE_CACHE[lang]
        try:
            voice = PiperVoice.load(str(model_path), config_path=str(config_path))
        except TypeError:
            voice = PiperVoice.load(str(model_path))
        _VOICE_CACHE[lang] = voice
        return voice


def warmup_piper_voices(langs: list[str] | None = None) -> dict[str, str]:
    results: dict[str, str] = {}
    for lang in langs or ["fr", "ar"]:
        normalized = "ar" if lang.startswith("ar") else "fr"
        try:
            voice = _get_piper_voice(normalized)
            results[normalized] = "loaded" if voice is not None else "python_api_unavailable"
        except Exception as exc:
            results[normalized] = f"error: {exc}"
    return results


def _run_piper_cli(text: str, lang: str, output_path: Path, speed: float) -> None:
    model_path, config_path = _voice_paths(lang)
    if not model_path.exists() or not config_path.exists():
        raise TTSError(
            f"Voix Piper '{lang}' introuvable. Modèle attendu: {model_path}. "
            "Lance: python download_piper_voices.py"
        )

    speed = max(0.60, min(float(speed or 1.0), 1.90))
    length_scale = max(0.50, min(1.80, 1.0 / speed))

    commands: list[list[str]] = []
    piper_bin = _piper_binary()
    if piper_bin:
        commands.append([
            piper_bin,
            "--model", str(model_path),
            "--config", str(config_path),
            "--output_file", str(output_path),
            "--length_scale", str(length_scale),
        ])
    commands.append([
        sys.executable,
        "-m", "piper",
        "--model", str(model_path),
        "--config", str(config_path),
        "--output_file", str(output_path),
        "--length_scale", str(length_scale),
    ])

    errors = []
    for command in commands:
        try:
            result = subprocess.run(
                command,
                input=text.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
            )
            if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 44:
                return
            errors.append(result.stderr.decode("utf-8", errors="ignore")[-1500:])
        except Exception as exc:
            errors.append(str(exc))

    raise TTSError(
        "Piper n'a pas réussi à générer l'audio. "
        "Vérifie: pip install piper-tts et python download_piper_voices.py. "
        f"Détails: {' | '.join(errors[-2:])}"
    )


def _run_piper_python_api(text: str, lang: str, output_path: Path, speed: float) -> bool:
    voice = _get_piper_voice(lang)
    if voice is None:
        return False

    speed = max(0.60, min(float(speed or 1.0), 1.90))
    length_scale = max(0.50, min(1.80, 1.0 / speed))

    try:
        # Synthesis is protected per language. This avoids multiple simultaneous
        # heavy ONNX runs that make CPU generation much slower.
        with _VOICE_SYNTH_LOCKS.setdefault(lang, threading.RLock()):
            with wave.open(str(output_path), "wb") as wav_file:
                try:
                    voice.synthesize_wav(text, wav_file, length_scale=length_scale)
                except TypeError:
                    voice.synthesize_wav(text, wav_file)
        return output_path.exists() and output_path.stat().st_size > 44
    except Exception:
        return False


def _synthesize_with_pyttsx3(text: str, output_path: Path, lang: str, speed: float) -> None:
    try:
        import pyttsx3
    except Exception as exc:
        raise TTSError(f"pyttsx3 n'est pas installé: {exc}")

    if lang == "ar":
        raise TTSError(
            "TTS arabe non disponible via pyttsx3. Utilise Piper: "
            "pip install piper-tts puis python download_piper_voices.py"
        )

    engine = pyttsx3.init()
    try:
        voices = engine.getProperty("voices") or []
        for voice in voices:
            voice_text = f"{voice.id} {voice.name}".lower()
            if any(token in voice_text for token in ["french", "français", "france", "hortense", "denise"]):
                engine.setProperty("voice", voice.id)
                break
        default_rate = int(engine.getProperty("rate") or 180)
        engine.setProperty("rate", int(default_rate * max(0.60, min(speed, 1.90))))
        engine.save_to_file(text, str(output_path))
        engine.runAndWait()
    finally:
        try:
            engine.stop()
        except Exception:
            pass

    if not output_path.exists() or output_path.stat().st_size <= 44:
        raise TTSError("pyttsx3 n'a pas généré de fichier audio valide.")


def _trim_wav_silence(wav_path: Path, threshold: int = 300, padding_ms: int = 45) -> None:
    try:
        with wave.open(str(wav_path), "rb") as wav_in:
            params = wav_in.getparams()
            channels = wav_in.getnchannels()
            sample_width = wav_in.getsampwidth()
            frame_rate = wav_in.getframerate()
            n_frames = wav_in.getnframes()
            raw = wav_in.readframes(n_frames)

        if sample_width != 2 or channels < 1 or n_frames <= 0:
            return

        import array
        samples = array.array("h")
        samples.frombytes(raw)
        if sys.byteorder != "little":
            samples.byteswap()

        frame_count = len(samples) // channels
        if frame_count <= 0:
            return

        def frame_level(frame_index: int) -> int:
            start = frame_index * channels
            end = start + channels
            return max(abs(int(value)) for value in samples[start:end])

        start_frame = 0
        while start_frame < frame_count and frame_level(start_frame) <= threshold:
            start_frame += 1

        end_frame = frame_count - 1
        while end_frame > start_frame and frame_level(end_frame) <= threshold:
            end_frame -= 1

        if start_frame >= end_frame:
            return

        padding_frames = int(frame_rate * padding_ms / 1000)
        start_frame = max(0, start_frame - padding_frames)
        end_frame = min(frame_count - 1, end_frame + padding_frames)

        removed_frames = start_frame + (frame_count - 1 - end_frame)
        if removed_frames < int(frame_rate * 0.08):
            return

        trimmed = samples[start_frame * channels:(end_frame + 1) * channels]
        if sys.byteorder != "little":
            trimmed.byteswap()

        with wave.open(str(wav_path), "wb") as wav_out:
            wav_out.setparams(params)
            wav_out.writeframes(trimmed.tobytes())
    except Exception:
        return


def synthesize_to_wav(text: str, lang: str = "auto", speed: float | None = None) -> str:
    prepared_text = prepare_text_for_tts(text, lang)
    if not prepared_text:
        raise TTSError("Texte vide ou non lisible pour la lecture vocale.")

    resolved_lang = normalize_tts_lang(lang, prepared_text)
    if not _is_safe_chunk(prepared_text, resolved_lang):
        raise TTSError("Morceau TTS ignoré: texte trop ambigu ou non supporté par la voix locale.")

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    configured_speed = float(speed or PIPER_VOICES.get(resolved_lang, {}).get("default_speed", 1.0))
    output_path = GENERATED_DIR / f"tts_{resolved_lang}_{uuid.uuid4().hex}.wav"

    if resolved_lang in {"fr", "ar"}:
        try:
            if _run_piper_python_api(prepared_text, resolved_lang, output_path, configured_speed):
                _trim_wav_silence(output_path)
                return str(output_path)
        except TTSError:
            raise
        except Exception:
            pass

        _run_piper_cli(prepared_text, resolved_lang, output_path, configured_speed)
        _trim_wav_silence(output_path)
        return str(output_path)

    _synthesize_with_pyttsx3(prepared_text, output_path, "fr", configured_speed)
    _trim_wav_silence(output_path)
    return str(output_path)


def tts_debug_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "python_executable": sys.executable,
        "piper_binary": _piper_binary(),
        "piper_module_installed": _piper_installed_as_module(),
        "voices_dir": str(PIPER_VOICES_DIR),
        "safe_tts_mode": True,
        "wav_silence_trim": True,
        "piper_voice_cache_enabled": True,
        "cached_voices": sorted(_VOICE_CACHE.keys()),
        "voices": {},
    }
    for lang, voice_info in PIPER_VOICES.items():
        model_path, config_path = _voice_paths(lang)
        info["voices"][lang] = {
            "label": voice_info["label"],
            "model": str(model_path),
            "config": str(config_path),
            "model_installed": model_path.exists(),
            "config_installed": config_path.exists(),
            "default_speed": voice_info.get("default_speed"),
            "recommended_range": voice_info.get("recommended_range"),
            "cached": lang in _VOICE_CACHE,
        }
    return info
