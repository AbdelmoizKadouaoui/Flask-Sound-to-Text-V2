import glob
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
import wave
from functools import lru_cache
from pathlib import Path

import pyttsx3

from config import GENERATED_DIR, PIPER_VOICES


class TTSError(RuntimeError):
    pass


# Réglages vitesse audio.
# 1.00 = normal. 1.15 = 15% plus rapide.
DEFAULT_TTS_SPEED = {
    "fr": 1.00,
    "ar": 1.15,
}

PIPER_SYNTHESIS_LOCK = threading.Lock()


def _ensure_dir() -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)


def _normalize_lang(lang: str) -> str:
    if (lang or "").startswith("ar"):
        return "ar"
    return "fr"


def _voice_paths(lang: str) -> tuple[Path | None, Path | None]:
    normalized = _normalize_lang(lang)
    info = PIPER_VOICES.get(normalized)
    if not info:
        return None, None
    return Path(info["model"]), Path(info["config"])


def _safe_speed(speed: float | int | str | None, lang: str) -> float:
    normalized = _normalize_lang(lang)
    default = DEFAULT_TTS_SPEED.get(normalized, 1.0)

    if speed is None or speed == "":
        return default

    try:
        value = float(speed)
    except (TypeError, ValueError):
        return default

    # Limites volontairement prudentes pour garder une voix naturelle.
    return max(0.75, min(value, 1.45))


def _ffmpeg_exe() -> str | None:
    env_path = os.getenv("FFMPEG_PATH")
    if env_path and Path(env_path).exists():
        return env_path
    return shutil.which("ffmpeg")


def _atempo_filters(speed: float) -> str:
    """
    ffmpeg atempo accepte en pratique des facteurs entre 0.5 et 2.0.
    Cette fonction chain les filtres si besoin.
    """
    factors: list[float] = []
    remaining = float(speed)

    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0

    while remaining < 0.5:
        factors.append(0.5)
        remaining /= 0.5

    factors.append(remaining)
    return ",".join(f"atempo={factor:.4f}" for factor in factors)


def _apply_audio_speed(input_path: Path, speed: float) -> Path:
    if abs(speed - 1.0) < 0.02:
        return input_path

    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        # Pas bloquant: on retourne l'audio original.
        return input_path

    output_path = input_path.with_name(f"{input_path.stem}_speed_{str(speed).replace('.', '_')}.wav")

    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-filter:a",
        _atempo_filters(speed),
        str(output_path),
    ]

    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            try:
                input_path.unlink(missing_ok=True)
            except Exception:
                pass
            return output_path
    except Exception:
        pass

    return input_path


def _piper_import_status() -> dict:
    try:
        import piper  # noqa: F401
        from piper import PiperVoice  # noqa: F401

        return {"ok": True, "error": None}
    except Exception as exc:
        return {"ok": False, "error": repr(exc)}


@lru_cache(maxsize=4)
def _load_piper_voice_cached(model_path_str: str, config_path_str: str | None):
    """
    Charge la voix Piper une seule fois et la réutilise.
    Important pour réduire fortement le délai à partir de la deuxième lecture.
    """
    from piper import PiperVoice

    model_path = Path(model_path_str)
    config_path = Path(config_path_str) if config_path_str else None

    try:
        return PiperVoice.load(str(model_path))
    except TypeError:
        if config_path and config_path.exists():
            return PiperVoice.load(str(model_path), str(config_path))
        raise


def _speak_with_piper_api(text: str, output_path: Path, lang: str) -> tuple[bool, str | None]:
    model_path, config_path = _voice_paths(lang)

    if not model_path or not model_path.exists():
        return False, f"Modèle Piper introuvable: {model_path}"

    if not config_path or not config_path.exists():
        return False, f"Config Piper introuvable: {config_path}"

    try:
        voice = _load_piper_voice_cached(str(model_path), str(config_path))
        with PIPER_SYNTHESIS_LOCK:
            with wave.open(str(output_path), "wb") as wav_file:
                voice.synthesize_wav(text, wav_file)

        if output_path.exists() and output_path.stat().st_size > 0:
            return True, None

        return False, "Piper API a fini sans créer de fichier audio."
    except ModuleNotFoundError as exc:
        return False, f"Package piper-tts non installé dans ce Python ({sys.executable}): {exc}"
    except Exception as exc:
        return False, f"Erreur Piper API: {repr(exc)}"


def _piper_command_candidates() -> list[list[str]]:
    candidates: list[list[str]] = []

    env_exe = os.getenv("PIPER_EXE")
    if env_exe:
        candidates.append([env_exe])

    for executable in ("piper", "piper.exe", "piper-tts", "piper-tts.exe"):
        found = shutil.which(executable)
        if found:
            candidates.append([found])

    local_candidates = [
        Path(__file__).resolve().parents[1] / "piper" / "piper.exe",
        Path(__file__).resolve().parents[1] / "piper.exe",
        Path(__file__).resolve().parents[1] / "piper" / "piper",
    ]
    for local_exe in local_candidates:
        if local_exe.exists():
            candidates.append([str(local_exe)])

    scripts_dir = Path(sys.executable).resolve().parent
    for name in ("piper.exe", "piper-tts.exe", "piper"):
        candidate = scripts_dir / name
        if candidate.exists():
            candidates.append([str(candidate)])

    unique: list[list[str]] = []
    seen = set()
    for cmd in candidates:
        key = tuple(cmd)
        if key not in seen:
            unique.append(cmd)
            seen.add(key)

    return unique


def _speak_with_piper_cli(text: str, output_path: Path, lang: str) -> tuple[bool, str | None]:
    model_path, config_path = _voice_paths(lang)

    if not model_path or not model_path.exists():
        return False, f"Modèle Piper introuvable: {model_path}"

    cmd_suffix = ["--model", str(model_path), "--output_file", str(output_path)]
    if config_path and config_path.exists():
        cmd_suffix.extend(["--config", str(config_path)])

    errors: list[str] = []

    for cmd_prefix in _piper_command_candidates():
        cmd = cmd_prefix + cmd_suffix
        try:
            result = subprocess.run(
                cmd,
                input=text,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
            )
        except FileNotFoundError:
            continue
        except Exception as exc:
            errors.append(f"{' '.join(cmd_prefix)}: {repr(exc)}")
            continue

        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            return True, None

        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        errors.append(f"{' '.join(cmd_prefix)}: {stderr or stdout or 'échec sans détail'}")

    if not errors:
        return False, "Aucune commande Piper trouvée."

    return False, " | ".join(errors[-3:])


def _speak_with_pyttsx3(text: str, output_path: Path, lang: str = "fr") -> None:
    try:
        engine = pyttsx3.init()
        engine.setProperty("rate", 175 if _normalize_lang(lang) == "fr" else 165)
        engine.setProperty("volume", 1.0)

        wanted_keywords = {
            "fr": ["french", "francais", "français", "fr-fr", "hortense", "thomas"],
            "ar": ["arabic", "arabe", "ar-", "ar_sa", "ar-sa", "ar_eg", "ar-eg"],
        }.get(_normalize_lang(lang), [])

        voices = engine.getProperty("voices") or []
        selected = False

        for voice in voices:
            haystack = " ".join(
                [
                    str(getattr(voice, "id", "")),
                    str(getattr(voice, "name", "")),
                    " ".join([str(x) for x in getattr(voice, "languages", []) or []]),
                ]
            ).lower()
            if any(keyword in haystack for keyword in wanted_keywords):
                engine.setProperty("voice", voice.id)
                selected = True
                break

        if _normalize_lang(lang) == "ar" and not selected:
            raise TTSError("Aucune voix arabe Windows/pyttsx3 trouvée.")

        engine.save_to_file(text, str(output_path))
        engine.runAndWait()
    except TTSError:
        raise
    except Exception as exc:
        raise TTSError(str(exc)) from exc


def split_text_for_tts(text: str, max_chars: int = 180) -> list[str]:
    """
    Découpe un texte long en chunks lisibles.
    Le navigateur peut lire le premier chunk pendant que le backend génère le suivant.
    """
    clean = re.sub(r"\s+", " ", (text or "").strip())
    if not clean:
        return []

    # Coupe après ponctuation française/arabe/anglaise.
    sentence_parts = re.split(r"(?<=[\.\!\?؟؛،،:;])\s+", clean)

    chunks: list[str] = []
    current = ""

    for part in sentence_parts:
        part = part.strip()
        if not part:
            continue

        # Si une phrase est trop longue, coupe par groupes de mots.
        if len(part) > max_chars:
            words = part.split(" ")
            buffer = ""
            for word in words:
                candidate = f"{buffer} {word}".strip()
                if len(candidate) <= max_chars:
                    buffer = candidate
                else:
                    if buffer:
                        if current:
                            chunks.append(current.strip())
                            current = ""
                        chunks.append(buffer.strip())
                    buffer = word
            if buffer:
                part = buffer
            else:
                continue

        candidate = f"{current} {part}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current.strip())
            current = part
        else:
            current = candidate

    if current:
        chunks.append(current.strip())

    return chunks or [clean]


def tts_status() -> dict:
    voices = {}
    for lang in sorted({"fr", "ar"}):
        model_path, config_path = _voice_paths(lang)
        voices[lang] = {
            "model": str(model_path) if model_path else None,
            "model_installed": bool(model_path and model_path.exists()),
            "config": str(config_path) if config_path else None,
            "config_installed": bool(config_path and config_path.exists()),
            "default_speed": DEFAULT_TTS_SPEED.get(lang, 1.0),
        }

    import_status = _piper_import_status()
    commands = _piper_command_candidates()

    return {
        "python_executable_used_by_flask": sys.executable,
        "piper_python_api_import": import_status,
        "piper_commands_checked": [" ".join(cmd) for cmd in commands],
        "piper_command_found": any(Path(cmd[0]).exists() for cmd in commands if len(cmd) == 1),
        "voices": voices,
        "chunked_tts": True,
        "fix_command_same_python": f'"{sys.executable}" -m pip install piper-tts',
        "hint_arabic": "Pour accélérer un peu l'arabe, le backend applique par défaut un atempo ffmpeg de 1.15 après génération Piper.",
    }


def synthesize_to_wav(text: str, lang: str = "fr", speed: float | int | str | None = None) -> Path:
    _ensure_dir()

    if not text or not text.strip():
        raise TTSError("Texte vide.")

    safe_text = text.strip()[:2000]
    output_path = GENERATED_DIR / f"tts_{uuid.uuid4().hex}.wav"
    normalized = _normalize_lang(lang)
    final_speed = _safe_speed(speed, normalized)

    piper_errors: list[str] = []

    # Piper en premier, surtout pour l'arabe.
    piper_ok, piper_error = _speak_with_piper_api(safe_text, output_path, normalized)
    if not piper_ok and piper_error:
        piper_errors.append(piper_error)

    if not piper_ok:
        piper_ok, piper_error = _speak_with_piper_cli(safe_text, output_path, normalized)
        if not piper_ok and piper_error:
            piper_errors.append(piper_error)

    if not piper_ok:
        if normalized == "ar":
            model_path, config_path = _voice_paths("ar")
            details = " | ".join(piper_errors[-4:]) or "aucun détail"
            raise TTSError(
                "TTS arabe non disponible. Les fichiers voix existent peut-être, mais Piper n'est pas utilisable par le Python qui lance Flask. "
                f"Python Flask: {sys.executable}. "
                f"Modèle attendu: {model_path}. Config attendue: {config_path}. "
                f"Commande fix: \"{sys.executable}\" -m pip install piper-tts. "
                f"Détails Piper: {details}"
            )

        # Français: fallback pyttsx3 si Piper échoue.
        _speak_with_pyttsx3(safe_text, output_path, lang=normalized)

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise TTSError("Aucun fichier audio généré. Vérifie les voix TTS installées.")

    return _apply_audio_speed(output_path, final_speed)
