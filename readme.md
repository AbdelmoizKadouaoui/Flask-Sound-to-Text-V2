# Flask Voice Chatbot Offline - Optimal Realtime TTS

Prototype Flask local avec:

- Interface chat style WhatsApp / ChatGPT.
- Record micro avec `MediaRecorder`.
- Animation wave seulement quand une voix est détectée.
- STT offline avec Vosk, détection auto FR/AR.
- TTS offline avec Piper, détection auto FR/AR.
- TTS pipeline: le premier morceau est lu dès qu'il est prêt, pendant que le morceau suivant est généré.
- Cache Piper côté Flask: les voix FR/AR sont chargées une seule fois en mémoire, au lieu d'être rechargées à chaque chunk.
- Préchargement limité à 1 chunk d'avance: pas de surcharge CPU comme avec plusieurs générations parallèles.
- Réglages de vitesse FR et AR dans l'interface.
- Nettoyage safe du texte avant TTS pour éviter les sons instables.
- Suppression automatique du silence au début/fin des WAV.

## Installation

```powershell
cd flask_voice_chatbot_optimal_realtime_tts
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Si tu utilises ton Python 3.11 directement:

```powershell
& C:\Users\arabe\AppData\Local\Programs\Python\Python311\python.exe -m pip install -r requirements.txt
```

## Télécharger les modèles Vosk

```powershell
python download_models.py
```

## Télécharger les voix Piper

```powershell
python download_piper_voices.py
```

## Lancer Flask

```powershell
python app.py
```

Puis ouvrir:

```text
http://127.0.0.1:5000
```

## Pourquoi cette version est plus rapide

Les versions précédentes pouvaient être lentes car elles lançaient trop de générations Piper en parallèle ou rechargeaient la voix ONNX pour chaque petit fichier audio.

Cette version fait trois optimisations:

1. `PiperVoice` est gardé en mémoire dans `services/tts_local.py`.
2. Le navigateur ne garde qu'un seul morceau d'avance dans la file.
3. Flask tourne avec `threaded=True`, mais la synthèse Piper est protégée par un lock par langue pour éviter de surcharger le CPU.

## Debug

FFmpeg:

```text
http://127.0.0.1:5000/api/debug/ffmpeg
```

TTS/Piper/cache:

```text
http://127.0.0.1:5000/api/debug/tts
```

Tu dois voir:

```json
"piper_voice_cache_enabled": true
```

Après une lecture, `cached_voices` doit contenir `fr` ou `ar`.
