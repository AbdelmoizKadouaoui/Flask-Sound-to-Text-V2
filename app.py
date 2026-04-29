import glob
import os
import shutil
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from config import DEFAULT_STT_LANG, GENERATED_DIR, MAX_CONTENT_LENGTH


def find_ffmpeg() -> str | None:
    candidates = []

    env_path = os.getenv("FFMPEG_PATH")
    if env_path:
        candidates.append(env_path)

    path_ffmpeg = shutil.which("ffmpeg")
    if path_ffmpeg:
        candidates.append(path_ffmpeg)

    candidates.extend(
        [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
        ]
    )

    winget_patterns = [
        r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\**\ffmpeg.exe",
        r"%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe",
        r"%LOCALAPPDATA%\Microsoft\WindowsApps\ffmpeg.exe",
    ]

    for pattern in winget_patterns:
        matches = glob.glob(os.path.expandvars(pattern), recursive=True)
        candidates.extend(matches)

    search_dirs = [
        Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages",
        Path("C:/Program Files"),
        Path("C:/Program Files (x86)"),
    ]

    for base_dir in search_dirs:
        if base_dir.exists():
            try:
                candidates.extend(str(match) for match in base_dir.rglob("ffmpeg.exe"))
            except Exception:
                pass

    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(Path(candidate).resolve())

    return None


def configure_ffmpeg_path() -> str | None:
    ffmpeg_exe = find_ffmpeg()

    if not ffmpeg_exe:
        print("ATTENTION: ffmpeg.exe introuvable.")
        print("Commande Windows possible: winget install Gyan.FFmpeg")
        return None

    ffmpeg_dir = str(Path(ffmpeg_exe).parent)
    current_path = os.environ.get("PATH", "")
    if ffmpeg_dir not in current_path:
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + current_path

    os.environ["FFMPEG_PATH"] = ffmpeg_exe
    print(f"FFmpeg trouvé: {ffmpeg_exe}")
    return ffmpeg_exe


FFMPEG_EXE = configure_ffmpeg_path()

from services.stt_vosk import STTError, available_languages, transcribe_audio
from services.tts_local import (
    TTSError,
    detect_text_language,
    normalize_tts_lang,
    split_text_into_tts_units,
    synthesize_to_wav,
    tts_debug_info,
    warmup_piper_voices,
)


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

GENERATED_DIR.mkdir(parents=True, exist_ok=True)


def simple_local_bot(message: str, lang: str = "auto") -> str:
    """
    Demo bot only.
    Important for this prototype: return exactly the received text.
    Replace this function with your real chatbot later.
    """
    return (message or "").strip()


@app.get("/")
def index():
    return render_template("index.html", default_lang=DEFAULT_STT_LANG)


@app.get("/api/languages")
def languages():
    return jsonify({"languages": available_languages(), "default": DEFAULT_STT_LANG})


@app.get("/api/debug/ffmpeg")
def debug_ffmpeg():
    return jsonify(
        {
            "ok": FFMPEG_EXE is not None,
            "ffmpeg_exe": FFMPEG_EXE,
            "shutil_which_ffmpeg": shutil.which("ffmpeg"),
            "ffmpeg_path_env": os.getenv("FFMPEG_PATH"),
        }
    )


@app.get("/api/debug/tts")
def debug_tts():
    return jsonify(tts_debug_info())


@app.post("/api/detect-language")
def detect_language():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    lang = detect_text_language(text)
    return jsonify({"ok": True, "lang": lang})


@app.post("/api/stt")
def stt():
    lang = request.form.get("lang", DEFAULT_STT_LANG)
    audio_file = request.files.get("audio")

    if not audio_file:
        return jsonify({"ok": False, "error": "Aucun fichier audio reçu."}), 400

    try:
        text, meta = transcribe_audio(audio_file, lang)
        return jsonify({"ok": True, "text": text, "meta": meta})
    except STTError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Erreur STT inattendue: {exc}"}), 500


@app.post("/api/chat")
def chat():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    lang = data.get("lang", "auto")
    reply = simple_local_bot(message, lang)
    resolved_lang = normalize_tts_lang("auto", reply or message)
    return jsonify({"ok": True, "reply": reply, "lang": resolved_lang})


@app.post("/api/tts/chunks")
def tts_chunks():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    lang = data.get("lang", "auto")
    max_chars = data.get("max_chars")

    try:
        resolved_lang = normalize_tts_lang(lang, text)
        chunks = split_text_into_tts_units(text, lang, int(max_chars) if max_chars else None)
        return jsonify({"ok": True, "lang": resolved_lang, "chunks": chunks, "cached_tts": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Erreur découpage TTS: {exc}"}), 500


@app.post("/api/tts/warmup")
def tts_warmup():
    data = request.get_json(silent=True) or {}
    langs = data.get("langs") or ["fr", "ar"]
    try:
        return jsonify({"ok": True, "results": warmup_piper_voices(langs)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/tts/chunk")
def tts_chunk():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    lang = data.get("lang", "auto")
    speed = data.get("speed")

    try:
        resolved_lang = normalize_tts_lang(lang, text)
        audio_path = synthesize_to_wav(text, lang=resolved_lang, speed=float(speed) if speed else None)
        return send_file(
            Path(audio_path),
            mimetype="audio/wav",
            as_attachment=False,
            download_name="response_chunk.wav",
        )
    except TTSError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Erreur TTS inattendue: {exc}"}), 500


@app.post("/api/tts")
def tts():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    lang = data.get("lang", "auto")
    speed = data.get("speed")

    try:
        resolved_lang = normalize_tts_lang(lang, text)
        audio_path = synthesize_to_wav(text, lang=resolved_lang, speed=float(speed) if speed else None)
        return send_file(
            Path(audio_path),
            mimetype="audio/wav",
            as_attachment=False,
            download_name="response.wav",
        )
    except TTSError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Erreur TTS inattendue: {exc}"}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True, threaded=True)
