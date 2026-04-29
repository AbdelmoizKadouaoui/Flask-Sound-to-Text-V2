from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"
PIPER_VOICES_DIR = BASE_DIR / "piper_voices"
GENERATED_DIR = BASE_DIR / "static" / "generated"
UPLOAD_DIR = BASE_DIR / "tmp_uploads"

# Vosk STT models. Download all with: python download_models.py
VOSK_MODELS = {
    "fr": {
        "label": "Français - Vosk big 0.22",
        "path": MODELS_DIR / "vosk-model-fr-0.22",
        "url": "https://alphacephei.com/vosk/models/vosk-model-fr-0.22.zip",
    },
    "ar": {
        "label": "Arabic MSA - MGB2 0.4 recommandé",
        "path": MODELS_DIR / "vosk-model-ar-mgb2-0.4",
        "url": "https://alphacephei.com/vosk/models/vosk-model-ar-mgb2-0.4.zip",
    },
    "ar_linto": {
        "label": "Arabic - LinTO big 1.1.0 optionnel",
        "path": MODELS_DIR / "vosk-model-ar-0.22-linto-1.1.0",
        "url": "https://alphacephei.com/vosk/models/vosk-model-ar-0.22-linto-1.1.0.zip",
    },
}

# Piper local TTS voices. Download all with: python download_piper_voices.py
# Piper engine is installed with: pip install -r requirements.txt
PIPER_VOICES = {
    "fr": {
        "label": "Piper French mls medium",
        "model": PIPER_VOICES_DIR / "fr_FR-mls-medium.onnx",
        "config": PIPER_VOICES_DIR / "fr_FR-mls-medium.onnx.json",
        "model_url": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fr/fr_FR/mls/medium/fr_FR-mls-medium.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fr/fr_FR/mls/medium/fr_FR-mls-medium.onnx.json",
    },
    "ar": {
        "label": "Piper Arabic ar_JO kareem medium",
        "model": PIPER_VOICES_DIR / "ar_JO-kareem-medium.onnx",
        "config": PIPER_VOICES_DIR / "ar_JO-kareem-medium.onnx.json",
        "model_url": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx.json",
    },
    "ar_linto": {
        "label": "Piper Arabic ar_JO kareem medium",
        "model": PIPER_VOICES_DIR / "ar_JO-kareem-medium.onnx",
        "config": PIPER_VOICES_DIR / "ar_JO-kareem-medium.onnx.json",
        "model_url": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx.json",
    },
}

DEFAULT_STT_LANG = "fr"
MAX_CONTENT_LENGTH = 30 * 1024 * 1024  # 30 MB audio upload limit
