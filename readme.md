# Flask Voice Chatbot Offline

Prototype Flask local avec:

- UI style WhatsApp / ChatGPT.
- Input texte.
- Record micro avec `MediaRecorder`.
- Animation wave seulement quand le micro détecte une voix assez forte.
- STT offline avec Vosk.
- TTS local avec Piper si disponible, sinon fallback pyttsx3 pour le français.
- Lecture TTS optimisée par chunks: le premier morceau est lu rapidement, puis le suivant est généré pendant la lecture.
- Réponse de test = exactement le texte saisi ou transcrit.

## 1. Installation

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Si tu lances Flask avec ton Python global, installe Piper dans le même Python:

```powershell
& C:\Users\arabe\AppData\Local\Programs\Python\Python311\python.exe -m pip install -r requirements.txt
```

## 2. FFmpeg

Windows:

```powershell
winget install Gyan.FFmpeg
```

Le projet cherche automatiquement `ffmpeg.exe`. Tu peux vérifier avec:

```text
http://127.0.0.1:5000/api/debug/ffmpeg
```

FFmpeg est utilisé pour convertir l'audio microphone et pour accélérer légèrement le TTS arabe.

## 3. Télécharger les modèles Vosk STT

Le script télécharge tout sans arguments:

```powershell
python download_models.py
```

Cela télécharge:

- `vosk-model-fr-0.22`
- `vosk-model-ar-mgb2-0.4`
- `vosk-model-ar-0.22-linto-1.1.0`

Les modèles sont placés dans `models/`.

## 4. Télécharger les voix Piper TTS

Pour que l'arabe TTS marche localement:

```powershell
python download_piper_voices.py
```

Cela télécharge:

- Français: `fr_FR-mls-medium`
- Arabe: `ar_JO-kareem-medium`

Les voix sont placées dans `piper_voices/`.

Vérification TTS:

```text
http://127.0.0.1:5000/api/debug/tts
```

## 5. Lancer Flask

```powershell
python app.py
```

Puis ouvre:

```text
http://127.0.0.1:5000
```

## 6. TTS rapide par chunks

Le bouton haut-parleur n'attend plus que tout le texte soit converti en un seul fichier.

Le nouveau flux est:

1. `/api/tts/chunks` découpe le texte en phrases.
2. `/api/tts/chunk` génère le premier morceau audio.
3. Le navigateur lit ce premier morceau.
4. Pendant la lecture, le navigateur demande déjà le morceau suivant.

Résultat: pour un texte long, la lecture commence plus vite.

## 7. Vitesse arabe

Dans `static/js/app.js`, tu peux modifier cette fonction:

```javascript
function ttsSpeedForCurrentLanguage() {
  return currentLang().startsWith('ar') ? 1.15 : 1.0;
}
```

Valeurs utiles:

- `1.00`: vitesse normale.
- `1.10`: un peu plus rapide.
- `1.15`: recommandé dans ce projet.
- `1.20`: plus rapide, mais peut devenir moins naturel.

Tu peux aussi changer la taille des chunks:

```javascript
function ttsChunkSizeForCurrentLanguage() {
  return currentLang().startsWith('ar') ? 130 : 180;
}
```

Plus petit = première lecture plus rapide, mais plus de requêtes serveur.

## Notes importantes

- Les gros modèles Vosk ne sont pas inclus dans le ZIP.
- Les voix Piper ne sont pas incluses dans le ZIP.
- Après téléchargement, STT et TTS peuvent fonctionner localement sans Internet.
- `pyttsx3` utilise les voix installées dans Windows. Si Windows n'a pas de voix arabe, le TTS arabe ne marchera pas avec pyttsx3. Piper est donc le meilleur choix pour l'arabe.
- Pour intégrer ton vrai chatbot, modifie seulement `simple_local_bot()` dans `app.py`.

## Fix Piper arabe

Si la voix arabe `.onnx` existe mais que l'application dit que le TTS arabe est indisponible, c'est presque toujours que `piper-tts` n'est pas installé dans le même Python que Flask.

Ouvre `http://127.0.0.1:5000/api/debug/tts` et regarde `python_executable_used_by_flask` puis lance la commande indiquée dans `fix_command_same_python`.

Exemple Windows:

```powershell
& C:\Users\arabe\AppData\Local\Programs\Python\Python311\python.exe -m pip install piper-tts
```

Puis ferme et relance Flask.
