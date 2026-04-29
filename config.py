from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"
PIPER_VOICES_DIR = BASE_DIR / "piper_voices"
GENERATED_DIR = BASE_DIR / "generated"
UPLOADS_DIR = BASE_DIR / "uploads"
DOWNLOADS_DIR = BASE_DIR / "downloads"

MAX_CONTENT_LENGTH = 40 * 1024 * 1024
DEFAULT_STT_LANG = "auto"

# Vosk STT models. Arabic MGB2 is recommended by default; LinTO big is optional.
VOSK_MODELS = {
    "fr": {
        "label": "Français - Vosk big 0.22",
        "folder": "vosk-model-fr-0.22",
        "url": "https://alphacephei.com/vosk/models/vosk-model-fr-0.22.zip",
    },
    "ar": {
        "label": "Arabe - Vosk MGB2 0.4 recommandé",
        "folder": "vosk-model-ar-mgb2-0.4",
        "url": "https://alphacephei.com/vosk/models/vosk-model-ar-mgb2-0.4.zip",
    },
    "ar_linto": {
        "label": "Arabe - Vosk LinTO big 1.1.0 optionnel",
        "folder": "vosk-model-ar-0.22-linto-1.1.0",
        "url": "https://alphacephei.com/vosk/models/vosk-model-ar-0.22-linto-1.1.0.zip",
    },
}

# Piper TTS voices.
# FR default speed is slightly slower to improve clarity.
PIPER_VOICES = {
    "fr": {
        "label": "Piper French mls medium",
        "model": "fr_FR-mls-medium.onnx",
        "config": "fr_FR-mls-medium.onnx.json",
        "model_url": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fr/fr_FR/mls/medium/fr_FR-mls-medium.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fr/fr_FR/mls/medium/fr_FR-mls-medium.onnx.json",
        "default_speed": 0.94,
        "recommended_range": [0.80, 1.20],
    },
    "ar": {
        "label": "Piper Arabic ar_JO kareem medium",
        "model": "ar_JO-kareem-medium.onnx",
        "config": "ar_JO-kareem-medium.onnx.json",
        "model_url": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx.json",
        "default_speed": 1.55,
        "recommended_range": [1.00, 1.80],
    },
}
