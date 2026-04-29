const chatWindow = document.getElementById('chatWindow');
const messageInput = document.getElementById('messageInput');
const sendButton = document.getElementById('sendButton');
const micButton = document.getElementById('micButton');
const micIcon = document.getElementById('micIcon');
const speakButton = document.getElementById('speakButton');
const languageSelect = document.getElementById('languageSelect');
const statusText = document.getElementById('statusText');
const voiceWave = document.getElementById('voiceWave');

let mediaRecorder = null;
let recordedChunks = [];
let isRecording = false;
let lastAssistantText = '';
let audioContext = null;
let analyser = null;
let analyserSource = null;
let analyserFrame = null;
let voiceDetectedDuringRecord = false;
let lastVoiceStatusAt = 0;
let ttsSessionId = 0;
let activeAudio = null;

function currentLang() {
  return languageSelect.value || window.APP_DEFAULT_LANG || 'fr';
}

function containsArabic(text) {
  return /[\u0600-\u06FF]/.test(text || '');
}

function addMessage(role, text, extraClass = '') {
  const wrapper = document.createElement('div');
  wrapper.className = `message ${role} ${extraClass}`.trim();

  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = text;
  bubble.dir = containsArabic(text) ? 'rtl' : 'ltr';

  wrapper.appendChild(bubble);
  chatWindow.appendChild(wrapper);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return wrapper;
}

function setStatus(text) {
  statusText.textContent = text;
}

function resetStatusSoon(delay = 900) {
  setTimeout(() => setStatus('Offline Flask · Vosk STT · Piper/Local TTS'), delay);
}

function setBusy(disabled) {
  sendButton.disabled = disabled;
  speakButton.disabled = disabled;
  messageInput.disabled = disabled;
  if (!isRecording) micButton.disabled = disabled;
}

function getSupportedRecorderMime() {
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg;codecs=opus',
    'audio/ogg',
    'audio/mp4'
  ];

  if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return '';
  return candidates.find(type => MediaRecorder.isTypeSupported(type)) || '';
}

function extensionForMime(mimeType) {
  if ((mimeType || '').includes('ogg')) return 'ogg';
  if ((mimeType || '').includes('mp4')) return 'mp4';
  return 'webm';
}

async function loadLanguages() {
  try {
    const response = await fetch('/api/languages');
    const data = await response.json();
    languageSelect.innerHTML = '';

    Object.entries(data.languages).forEach(([key, item]) => {
      const option = document.createElement('option');
      option.value = key;
      option.textContent = `${item.label}${item.installed ? '' : ' · non installé'}`;
      option.disabled = !item.installed;
      languageSelect.appendChild(option);
    });

    const defaultLang = data.default || window.APP_DEFAULT_LANG || 'fr';
    if ([...languageSelect.options].some(opt => opt.value === defaultLang && !opt.disabled)) {
      languageSelect.value = defaultLang;
    } else {
      const firstEnabled = [...languageSelect.options].find(opt => !opt.disabled);
      if (firstEnabled) languageSelect.value = firstEnabled.value;
    }

    const installedCount = Object.values(data.languages).filter(x => x.installed).length;
    if (installedCount === 0) {
      addMessage('system', 'Aucun modèle Vosk installé. Lance: python download_models.py');
    }
  } catch (error) {
    addMessage('system', `Erreur chargement langues: ${error.message}`);
  }
}

async function requestBotReply(cleanText) {
  const typing = addMessage('assistant', 'Réponse en cours...', 'typing');
  setBusy(true);

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: cleanText, lang: currentLang() })
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || 'Erreur chat');

    typing.remove();
    lastAssistantText = data.reply;
    addMessage('assistant', data.reply);
  } catch (error) {
    typing.remove();
    addMessage('system', `Erreur chat: ${error.message}`);
  } finally {
    setBusy(false);
    messageInput.focus();
  }
}

async function sendToBot(text) {
  const clean = (text || '').trim();
  if (!clean) return;

  addMessage('user', clean);
  messageInput.value = '';
  await requestBotReply(clean);
}

async function handleTranscribedText(text) {
  const clean = (text || '').trim();
  if (!clean) {
    addMessage('system', 'Vosk n’a pas détecté de texte. Vérifie la langue choisie, parle plus clairement, ou augmente la durée.');
    return;
  }

  // Affiche aussi dans l'input pour confirmer visuellement ce qui a été extrait.
  messageInput.value = clean;
  addMessage('user', clean);
  messageInput.value = '';
  await requestBotReply(clean);
}

async function transcribeBlob(blob, extension) {
  const form = new FormData();
  form.append('audio', blob, `recording.${extension || 'webm'}`);
  form.append('lang', currentLang());

  setStatus('Transcription Vosk en cours...');
  const response = await fetch('/api/stt', {
    method: 'POST',
    body: form
  });

  const data = await response.json();
  if (!data.ok) throw new Error(data.error || 'Erreur STT');
  return data.text || '';
}

function startVoiceAnalyser(stream) {
  stopVoiceAnalyser();
  voiceDetectedDuringRecord = false;

  audioContext = new (window.AudioContext || window.webkitAudioContext)();
  analyser = audioContext.createAnalyser();
  analyser.fftSize = 2048;
  analyser.smoothingTimeConstant = 0.35;

  analyserSource = audioContext.createMediaStreamSource(stream);
  analyserSource.connect(analyser);

  const data = new Uint8Array(analyser.fftSize);
  const threshold = 0.035;

  function tick() {
    if (!isRecording || !analyser) return;

    analyser.getByteTimeDomainData(data);

    let sumSquares = 0;
    for (const value of data) {
      const normalized = (value - 128) / 128;
      sumSquares += normalized * normalized;
    }

    const rms = Math.sqrt(sumSquares / data.length);
    const voiceActive = rms > threshold;
    const now = Date.now();

    if (voiceActive) {
      voiceDetectedDuringRecord = true;
      micButton.classList.add('voice-active');
      voiceWave.classList.add('active');
      if (now - lastVoiceStatusAt > 500) {
        setStatus('Voix détectée... clique encore pour arrêter');
        lastVoiceStatusAt = now;
      }
    } else {
      micButton.classList.remove('voice-active');
      voiceWave.classList.remove('active');
      if (now - lastVoiceStatusAt > 900) {
        setStatus('Enregistrement... aucune voix forte détectée');
        lastVoiceStatusAt = now;
      }
    }

    analyserFrame = requestAnimationFrame(tick);
  }

  tick();
}

function stopVoiceAnalyser() {
  if (analyserFrame) {
    cancelAnimationFrame(analyserFrame);
    analyserFrame = null;
  }

  if (analyserSource) {
    try { analyserSource.disconnect(); } catch (_) {}
    analyserSource = null;
  }

  if (audioContext) {
    try { audioContext.close(); } catch (_) {}
    audioContext = null;
  }

  analyser = null;
  micButton.classList.remove('voice-active');
  voiceWave.classList.remove('active');
}

async function startRecording() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
    addMessage('system', 'Ton navigateur ne supporte pas getUserMedia/MediaRecorder. Utilise Chrome, Edge ou Firefox récent.');
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true
      }
    });

    recordedChunks = [];
    const mimeType = getSupportedRecorderMime();
    const recorderOptions = mimeType ? { mimeType } : undefined;
    mediaRecorder = new MediaRecorder(stream, recorderOptions);

    mediaRecorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) recordedChunks.push(event.data);
    };

    mediaRecorder.onerror = (event) => {
      addMessage('system', `Erreur MediaRecorder: ${event.error?.message || 'erreur inconnue'}`);
    };

    mediaRecorder.onstop = async () => {
      stream.getTracks().forEach(track => track.stop());
      stopVoiceAnalyser();

      micButton.classList.remove('recording');
      micIcon.textContent = '🎙️';
      isRecording = false;
      setBusy(false);

      const finalMime = mediaRecorder.mimeType || mimeType || 'audio/webm';
      const extension = extensionForMime(finalMime);
      const blob = new Blob(recordedChunks, { type: finalMime });

      if (!voiceDetectedDuringRecord) {
        addMessage('system', 'Aucune voix claire détectée par le micro. Je tente quand même la transcription si l’audio existe.');
      }

      if (blob.size < 1000) {
        setStatus('Audio trop court. Réessaie.');
        return;
      }

      const transcribing = addMessage('system', 'Transcription en cours...');

      try {
        const text = await transcribeBlob(blob, extension);
        transcribing.remove();
        setStatus('Transcription terminée');
        await handleTranscribedText(text);
        resetStatusSoon();
      } catch (error) {
        transcribing.remove();
        setStatus('Erreur STT');
        addMessage('system', `Erreur transcription: ${error.message}`);
      }
    };

    mediaRecorder.start();
    isRecording = true;
    setBusy(false);
    micButton.classList.add('recording');
    micIcon.textContent = '⏹️';
    setStatus('Enregistrement... parle maintenant');
    startVoiceAnalyser(stream);
  } catch (error) {
    addMessage('system', `Accès micro refusé ou indisponible: ${error.message}`);
  }
}

function stopRecording() {
  if (mediaRecorder && isRecording) {
    micButton.disabled = true;
    setStatus('Arrêt de l’enregistrement...');
    mediaRecorder.stop();
  }
}

function ttsSpeedForCurrentLanguage() {
  // L'arabe Piper peut sembler lent. 1.15 = 15% plus rapide.
  // Tu peux changer à 1.20 si tu veux encore plus rapide.
  return currentLang().startsWith('ar') ? 1.15 : 1.0;
}

function ttsChunkSizeForCurrentLanguage() {
  // Chunks plus courts = première lecture plus rapide, surtout pour l'arabe.
  return currentLang().startsWith('ar') ? 130 : 180;
}

async function getTtsChunks(text) {
  const response = await fetch('/api/tts/chunks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, max_chars: ttsChunkSizeForCurrentLanguage() })
  });

  const data = await response.json();
  if (!data.ok) throw new Error(data.error || 'Erreur préparation TTS');
  return data.chunks || [];
}

async function fetchTtsChunkAudio(chunkText, chunkIndex, chunkCount, sessionId) {
  if (sessionId !== ttsSessionId) throw new Error('Lecture annulée');

  const response = await fetch('/api/tts/chunk', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text: chunkText,
      lang: currentLang(),
      speed: ttsSpeedForCurrentLanguage()
    })
  });

  if (!response.ok) {
    let message = 'Erreur TTS';
    try {
      const err = await response.json();
      message = err.error || message;
    } catch (_) {}
    throw new Error(message);
  }

  const blob = await response.blob();
  return {
    index: chunkIndex,
    count: chunkCount,
    url: URL.createObjectURL(blob)
  };
}

function playAudioUrl(audioUrl, sessionId) {
  return new Promise((resolve, reject) => {
    if (sessionId !== ttsSessionId) {
      URL.revokeObjectURL(audioUrl);
      resolve();
      return;
    }

    const audio = new Audio(audioUrl);
    activeAudio = audio;

    audio.onended = () => {
      URL.revokeObjectURL(audioUrl);
      if (activeAudio === audio) activeAudio = null;
      resolve();
    };

    audio.onerror = () => {
      URL.revokeObjectURL(audioUrl);
      if (activeAudio === audio) activeAudio = null;
      reject(new Error('Erreur lecture audio navigateur'));
    };

    audio.play().catch(error => {
      URL.revokeObjectURL(audioUrl);
      if (activeAudio === audio) activeAudio = null;
      reject(error);
    });
  });
}

async function speakLastAssistant() {
  const text = (lastAssistantText || '').trim();
  if (!text) {
    addMessage('system', 'Aucune réponse assistant à lire pour le moment.');
    return;
  }

  // Si une lecture précédente existe, on l'annule.
  ttsSessionId += 1;
  const sessionId = ttsSessionId;
  if (activeAudio) {
    try { activeAudio.pause(); } catch (_) {}
    activeAudio = null;
  }

  setStatus('Préparation lecture par phrases...');
  speakButton.disabled = true;

  try {
    const chunks = await getTtsChunks(text);
    if (!chunks.length) throw new Error('Aucun chunk TTS préparé');

    setStatus(`TTS: génération du premier morceau 1/${chunks.length}...`);

    let nextAudioPromise = fetchTtsChunkAudio(chunks[0].text, 0, chunks.length, sessionId);

    for (let index = 0; index < chunks.length; index += 1) {
      if (sessionId !== ttsSessionId) break;

      const currentAudio = await nextAudioPromise;

      // Prépare le morceau suivant pendant que le morceau courant est lu.
      if (index + 1 < chunks.length) {
        nextAudioPromise = fetchTtsChunkAudio(chunks[index + 1].text, index + 1, chunks.length, sessionId);
      } else {
        nextAudioPromise = null;
      }

      setStatus(`Lecture audio ${index + 1}/${chunks.length}...`);
      await playAudioUrl(currentAudio.url, sessionId);
    }

    if (sessionId === ttsSessionId) {
      setStatus('Lecture terminée');
    }
  } catch (error) {
    if (!String(error.message || '').includes('annulée')) {
      addMessage('system', `Erreur lecture vocale: ${error.message}`);
    }
  } finally {
    if (sessionId === ttsSessionId) {
      speakButton.disabled = false;
      resetStatusSoon();
    }
  }
}

sendButton.addEventListener('click', () => sendToBot(messageInput.value));
messageInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendToBot(messageInput.value);
  }
});

micButton.addEventListener('click', () => {
  if (isRecording) stopRecording();
  else startRecording();
});

speakButton.addEventListener('click', speakLastAssistant);

languageSelect.addEventListener('change', () => {
  const selected = languageSelect.options[languageSelect.selectedIndex]?.textContent || currentLang();
  setStatus(`Langue active: ${selected}`);
  resetStatusSoon(1500);
});

loadLanguages();
messageInput.focus();
