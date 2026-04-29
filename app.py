import glob
import os
import shutil
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from config import DEFAULT_STT_LANG, GENERATED_DIR, MAX_CONTENT_LENGTH


def find_ffmpeg() -> str | None:
    """
    Cherche ffmpeg.exe surtout sur Windows quand il est installé avec winget
    mais pas visible dans le PATH du process Flask.
    """
    candidates: list[str] = []

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
    """
    Ajoute automatiquement le dossier de ffmpeg.exe au PATH de Flask.
    Les services qui appellent simplement 'ffmpeg' peuvent ensuite le trouver.
    """
    ffmpeg_exe = find_ffmpeg()

    if not ffmpeg_exe:
        print("ATTENTION: ffmpeg.exe introuvable.")
        print("Installe FFmpeg ou ajoute son dossier bin au PATH.")
        print("Commande Windows: winget install Gyan.FFmpeg")
        return None

    ffmpeg_dir = str(Path(ffmpeg_exe).parent)
    current_path = os.environ.get("PATH", "")

    if ffmpeg_dir not in current_path:
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + current_path

    os.environ["FFMPEG_PATH"] = ffmpeg_exe

    print(f"FFmpeg trouvé: {ffmpeg_exe}")
    print(f"Dossier FFmpeg ajouté au PATH Flask: {ffmpeg_dir}")

    return ffmpeg_exe


# Important: configurer FFmpeg AVANT d'importer le service STT/TTS.
FFMPEG_EXE = configure_ffmpeg_path()

from services.stt_vosk import STTError, available_languages, transcribe_audio
from services.tts_local import TTSError, split_text_for_tts, synthesize_to_wav, tts_status


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

GENERATED_DIR.mkdir(parents=True, exist_ok=True)


def simple_local_bot(message: str, lang: str) -> str:
    """
    Demo bot only.

    Ici, la réponse est exactement le texte saisi ou détecté par STT.
    Quand tu vas intégrer ton vrai chatbot, remplace seulement cette fonction.
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
    return jsonify(tts_status())


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
    lang = data.get("lang", DEFAULT_STT_LANG)

    reply = simple_local_bot(message, lang)

    if not reply:
        return jsonify({"ok": False, "error": "Message vide."}), 400

    return jsonify({"ok": True, "reply": reply})


@app.post("/api/tts/chunks")
def tts_chunks():
    """
    Prépare un texte long pour une lecture optimisée.
    Le frontend lit le premier chunk pendant que le backend génère les suivants.
    """
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    max_chars = data.get("max_chars", 180)

    try:
        max_chars = int(max_chars)
    except (TypeError, ValueError):
        max_chars = 180

    max_chars = max(80, min(max_chars, 320))
    chunks = split_text_for_tts(text, max_chars=max_chars)

    if not chunks:
        return jsonify({"ok": False, "error": "Texte vide."}), 400

    return jsonify(
        {
            "ok": True,
            "chunks": [
                {"index": index, "text": chunk, "chars": len(chunk)}
                for index, chunk in enumerate(chunks)
            ],
            "count": len(chunks),
        }
    )


@app.post("/api/tts/chunk")
def tts_chunk():
    """
    Génère un seul morceau audio.
    """
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    lang = data.get("lang", DEFAULT_STT_LANG)
    speed = data.get("speed", None)

    try:
        audio_path = synthesize_to_wav(text, lang=lang, speed=speed)
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
    """
    Route de compatibilité: génère un seul fichier complet.
    Pour une lecture plus rapide, le frontend utilise /api/tts/chunks + /api/tts/chunk.
    """
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    lang = data.get("lang", DEFAULT_STT_LANG)
    speed = data.get("speed", None)

    try:
        audio_path = synthesize_to_wav(text, lang=lang, speed=speed)
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
