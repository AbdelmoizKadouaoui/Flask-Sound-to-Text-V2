const messagesEl = document.getElementById('messages');
const inputEl = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
const recordBtn = document.getElementById('recordBtn');
const speakLastBtn = document.getElementById('speakLastBtn');
const stopTtsBtn = document.getElementById('stopTtsBtn');
const autoTtsBtn = document.getElementById('autoTtsBtn');
const settingsBtn = document.getElementById('settingsBtn');
const settingsPanel = document.getElementById('settingsPanel');
const waveEl = document.getElementById('wave');
const statusBar = document.getElementById('statusBar');
const frSpeedRange = document.getElementById('frSpeedRange');
const arSpeedRange = document.getElementById('arSpeedRange');
const frSpeedValue = document.getElementById('frSpeedValue');
const arSpeedValue = document.getElementById('arSpeedValue');
const footerFrSpeed = document.getElementById('footerFrSpeed');
const footerArSpeed = document.getElementById('footerArSpeed');
const resetTtsSettingsBtn = document.getElementById('resetTtsSettingsBtn');

const DEFAULT_FR_TTS_SPEED = 0.94;
const DEFAULT_ARABIC_TTS_SPEED = 1.55;
const STORAGE_KEYS = {
  frSpeed: 'voiceChatTtsSpeedFr',
  arSpeed: 'voiceChatTtsSpeedAr',
  autoTts: 'voiceChatAutoTts',
};

let mediaRecorder = null;
let recordedChunks = [];
let audioContext = null;
let analyser = null;
let micStream = null;
let animationFrameId = null;
let heardVoiceDuringRecording = false;
let lastAssistantText = '';
let currentAudio = null;
let currentTtsToken = 0;
let autoTtsEnabled = false;
let ttsSettings = {
  fr: DEFAULT_FR_TTS_SPEED,
  ar: DEFAULT_ARABIC_TTS_SPEED,
};

function readNumberSetting(key, fallback) {
  const value = Number(localStorage.getItem(key));
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

function saveSettings() {
  localStorage.setItem(STORAGE_KEYS.frSpeed, String(ttsSettings.fr));
  localStorage.setItem(STORAGE_KEYS.arSpeed, String(ttsSettings.ar));
}

function loadSettings() {
  ttsSettings.fr = readNumberSetting(STORAGE_KEYS.frSpeed, DEFAULT_FR_TTS_SPEED);
  ttsSettings.ar = readNumberSetting(STORAGE_KEYS.arSpeed, DEFAULT_ARABIC_TTS_SPEED);
  autoTtsEnabled = localStorage.getItem(STORAGE_KEYS.autoTts) === 'true';
}

function refreshSettingsUi() {
  if (frSpeedRange) frSpeedRange.value = String(ttsSettings.fr);
  if (arSpeedRange) arSpeedRange.value = String(ttsSettings.ar);

  const frLabel = `${ttsSettings.fr.toFixed(2)}x`;
  const arLabel = `${ttsSettings.ar.toFixed(2)}x`;

  if (frSpeedValue) frSpeedValue.textContent = frLabel;
  if (arSpeedValue) arSpeedValue.textContent = arLabel;
  if (footerFrSpeed) footerFrSpeed.textContent = frLabel;
  if (footerArSpeed) footerArSpeed.textContent = arLabel;

  autoTtsBtn.classList.toggle('active', autoTtsEnabled);
  autoTtsBtn.setAttribute('aria-pressed', String(autoTtsEnabled));
  autoTtsBtn.textContent = autoTtsEnabled ? 'Auto TTS: ON' : 'Auto TTS: OFF';
}

function setStatus(message) {
  statusBar.textContent = message;
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function detectLanguageFromText(text) {
  const visible = (text || '').replace(/\s+/g, '');
  if (!visible) return 'fr';
  const arabicMatches = visible.match(/[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]/g) || [];
  return arabicMatches.length / visible.length >= 0.18 ? 'ar' : 'fr';
}

function ttsSpeedForText(text) {
  return detectLanguageFromText(text) === 'ar' ? ttsSettings.ar : ttsSettings.fr;
}

function chunkLimitForText(text) {
  // Balanced chunks: short enough to start fast, long enough to let the next
  // chunk generate while the current one is playing.
  return detectLanguageFromText(text) === 'ar' ? 160 : 180;
}

function normalizeTtsChunk(item, fallbackLang) {
  if (typeof item === 'string') {
    return { text: item, lang: fallbackLang || detectLanguageFromText(item) };
  }
  return {
    text: (item && item.text) ? item.text : '',
    lang: (item && item.lang) ? item.lang : fallbackLang,
  };
}

function addMessage(role, text) {
  const safeText = escapeHtml(text);

  if (role === 'system') {
    const el = document.createElement('div');
    el.className = 'system-line';
    el.innerHTML = safeText;
    messagesEl.appendChild(el);
    scrollToBottom();
    return el;
  }

  const wrapper = document.createElement('div');
  wrapper.className = `message ${role === 'user' ? 'user' : 'bot'}`;

  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.innerHTML = `<p>${safeText}</p>`;

  if (role === 'bot') {
    const speakButton = document.createElement('button');
    speakButton.className = 'bubble-speak';
    speakButton.type = 'button';
    speakButton.title = 'Lire ce texte';
    speakButton.textContent = '🔊';
    speakButton.addEventListener('click', () => playTextByChunks(text, { source: 'manual' }));
    bubble.appendChild(speakButton);
  }

  wrapper.appendChild(bubble);
  messagesEl.appendChild(wrapper);
  scrollToBottom();
  return wrapper;
}

function stopCurrentTts(silent = false) {
  currentTtsToken += 1;
  if (currentAudio) {
    try {
      currentAudio.pause();
      currentAudio.currentTime = 0;
    } catch (error) {
      // ignore
    }
  }
  currentAudio = null;
  if (!silent) {
    setStatus('Lecture vocale arrêtée.');
  }
}

async function getTtsChunks(text) {
  const response = await fetch('/api/tts/chunks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text,
      lang: 'auto',
      max_chars: chunkLimitForText(text),
    }),
  });

  const data = await response.json();
  if (!data.ok) {
    throw new Error(data.error || 'Erreur découpage TTS.');
  }
  return data;
}

async function fetchAudioChunk(chunkText, lang) {
  const response = await fetch('/api/tts/chunk', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text: chunkText,
      lang: lang || 'auto',
      speed: ttsSpeedForText(chunkText),
    }),
  });

  if (!response.ok) {
    let detail = 'Erreur lecture vocale.';
    try {
      const data = await response.json();
      detail = data.error || detail;
    } catch (error) {
      detail = await response.text();
    }
    throw new Error(detail);
  }

  const blob = await response.blob();
  return URL.createObjectURL(blob);
}

function playAudioUrl(url, token) {
  return new Promise((resolve, reject) => {
    if (token !== currentTtsToken) {
      resolve();
      return;
    }

    const audio = new Audio(url);
    currentAudio = audio;

    audio.onended = () => resolve();
    audio.onerror = () => reject(new Error('Le navigateur ne peut pas lire ce fichier audio.'));
    audio.play().catch(reject);
  });
}

async function playTextByChunks(text) {
  const cleanText = (text || '').trim();
  if (!cleanText) return;

  const token = ++currentTtsToken;
  const detectedLang = detectLanguageFromText(cleanText);
  setStatus(`Préparation TTS ${detectedLang.toUpperCase()} · mode pipeline...`);

  try {
    const chunkData = await getTtsChunks(cleanText);
    const fallbackLang = chunkData.lang || detectedLang;
    const chunks = (chunkData.chunks || [])
      .map((item) => normalizeTtsChunk(item, fallbackLang))
      .filter((item) => item.text && item.text.trim());

    if (!chunks.length) {
      setStatus('Aucun texte sûr à lire.');
      addMessage('system', 'TTS sécurisé: aucun morceau sûr à lire, donc la lecture a été ignorée.');
      return;
    }

    setStatus(`Lecture pipeline · ${chunks.length} morceau(x) · cache Piper actif · FR ${ttsSettings.fr.toFixed(2)}x / AR ${ttsSettings.ar.toFixed(2)}x`);

    // IMPORTANT: Only one chunk ahead. Previous versions started too many
    // Piper generations in parallel, which overloaded CPU and caused very long waits.
    const audioPromises = new Array(chunks.length);
    let nextToSchedule = 0;

    const scheduleNext = () => {
      if (nextToSchedule >= chunks.length) return;
      if (audioPromises[nextToSchedule]) return;

      const chunk = chunks[nextToSchedule];
      audioPromises[nextToSchedule] = fetchAudioChunk(chunk.text, chunk.lang || detectLanguageFromText(chunk.text));
      nextToSchedule += 1;
    };

    // Schedule first and second chunk only. Chunk 0 starts the audio quickly;
    // chunk 1 waits/generated in parallel while chunk 0 is being prepared/played.
    scheduleNext();
    scheduleNext();

    for (let index = 0; index < chunks.length; index += 1) {
      if (token !== currentTtsToken) return;

      let currentUrl = null;
      try {
        currentUrl = await audioPromises[index];
      } catch (error) {
        console.warn('Morceau TTS ignoré:', error);
      }

      // Keep exactly one chunk ahead after the current chunk is available.
      scheduleNext();

      if (currentUrl) {
        await playAudioUrl(currentUrl, token);
        URL.revokeObjectURL(currentUrl);
      }
    }

    if (token === currentTtsToken) {
      setStatus('Lecture terminée · pipeline TTS fluide.');
    }
  } catch (error) {
    if (token === currentTtsToken) {
      setStatus(`Erreur lecture vocale: ${error.message}`);
      addMessage('system', `Erreur lecture vocale: ${error.message}`);
    }
  }
}

async function sendMessage(text) {
  const message = (text || inputEl.value || '').trim();
  if (!message) return;

  addMessage('user', message);
  inputEl.value = '';
  setStatus('Envoi au chatbot local...');

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, lang: 'auto' }),
    });
    const data = await response.json();

    if (!data.ok) {
      throw new Error(data.error || 'Erreur chatbot.');
    }

    const reply = data.reply || '';
    lastAssistantText = reply;
    addMessage('bot', reply);
    setStatus(`Réponse prête · Langue TTS détectée: ${(data.lang || detectLanguageFromText(reply)).toUpperCase()}`);

    if (autoTtsEnabled) {
      playTextByChunks(reply);
    }
  } catch (error) {
    setStatus(`Erreur: ${error.message}`);
    addMessage('system', `Erreur: ${error.message}`);
  }
}

function setupAudioAnalyser(stream) {
  audioContext = new (window.AudioContext || window.webkitAudioContext)();
  const source = audioContext.createMediaStreamSource(stream);
  analyser = audioContext.createAnalyser();
  analyser.fftSize = 1024;
  source.connect(analyser);

  const data = new Uint8Array(analyser.fftSize);

  const tick = () => {
    if (!analyser) return;

    analyser.getByteTimeDomainData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i += 1) {
      const normalized = (data[i] - 128) / 128;
      sum += normalized * normalized;
    }
    const rms = Math.sqrt(sum / data.length);

    const voiceDetected = rms > 0.035;
    if (voiceDetected) {
      heardVoiceDuringRecording = true;
      waveEl.classList.add('active');
      setStatus('Voix détectée · enregistrement...');
    } else {
      waveEl.classList.remove('active');
      setStatus('Enregistrement... parle plus proche du micro si la wave ne bouge pas.');
    }

    animationFrameId = requestAnimationFrame(tick);
  };

  tick();
}

async function startRecording() {
  stopCurrentTts(true);
  recordedChunks = [];
  heardVoiceDuringRecording = false;

  try {
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    setupAudioAnalyser(micStream);

    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus'
      : 'audio/webm';

    mediaRecorder = new MediaRecorder(micStream, { mimeType });

    mediaRecorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        recordedChunks.push(event.data);
      }
    };

    mediaRecorder.onstop = handleRecordingStop;
    mediaRecorder.start();

    recordBtn.classList.add('recording');
    recordBtn.innerHTML = '<span class="mic-icon">⏹️</span>';
    setStatus('Enregistrement démarré...');
  } catch (error) {
    setStatus(`Erreur micro: ${error.message}`);
    addMessage('system', `Erreur micro: ${error.message}`);
  }
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
  }

  if (animationFrameId) {
    cancelAnimationFrame(animationFrameId);
    animationFrameId = null;
  }

  if (analyser) {
    analyser = null;
  }

  if (audioContext) {
    audioContext.close().catch(() => {});
    audioContext = null;
  }

  if (micStream) {
    micStream.getTracks().forEach((track) => track.stop());
    micStream = null;
  }

  waveEl.classList.remove('active');
  recordBtn.classList.remove('recording');
  recordBtn.innerHTML = '<span class="mic-icon">🎙️</span>';
}

async function handleRecordingStop() {
  stopRecording();

  if (!recordedChunks.length) {
    setStatus('Aucun audio enregistré.');
    addMessage('system', 'Aucun audio enregistré.');
    return;
  }

  if (!heardVoiceDuringRecording) {
    addMessage('system', 'Aucune voix claire détectée pendant le record. La transcription continue quand même.');
  }

  setStatus('Transcription Vosk auto FR/AR...');

  const blob = new Blob(recordedChunks, { type: recordedChunks[0]?.type || 'audio/webm' });
  const formData = new FormData();
  formData.append('audio', blob, 'recording.webm');
  formData.append('lang', 'auto');

  try {
    const response = await fetch('/api/stt', {
      method: 'POST',
      body: formData,
    });
    const data = await response.json();

    if (!data.ok) {
      throw new Error(data.error || 'Erreur transcription.');
    }

    const text = (data.text || '').trim();
    const detectedLang = data.meta?.lang || detectLanguageFromText(text);

    if (!text) {
      setStatus('Aucun texte détecté.');
      addMessage('system', 'Aucun texte détecté. Essaie de parler plus fort ou plus proche du micro.');
      return;
    }

    setStatus(`Transcription OK · modèle détecté: ${detectedLang.toUpperCase()}`);
    await sendMessage(text);
  } catch (error) {
    setStatus(`Erreur transcription: ${error.message}`);
    addMessage('system', `Erreur transcription: ${error.message}`);
  }
}

function toggleSettingsPanel() {
  const shouldShow = settingsPanel.classList.contains('hidden');
  settingsPanel.classList.toggle('hidden', !shouldShow);
  settingsPanel.setAttribute('aria-hidden', String(!shouldShow));
  settingsBtn.setAttribute('aria-expanded', String(shouldShow));
}

recordBtn.addEventListener('click', () => {
  if (mediaRecorder && mediaRecorder.state === 'recording') {
    stopRecording();
  } else {
    startRecording();
  }
});

sendBtn.addEventListener('click', () => sendMessage());

inputEl.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
});

speakLastBtn.addEventListener('click', () => {
  if (!lastAssistantText) {
    addMessage('system', 'Aucune réponse à lire pour le moment.');
    return;
  }
  playTextByChunks(lastAssistantText);
});

stopTtsBtn.addEventListener('click', () => stopCurrentTts());

autoTtsBtn.addEventListener('click', () => {
  autoTtsEnabled = !autoTtsEnabled;
  localStorage.setItem(STORAGE_KEYS.autoTts, String(autoTtsEnabled));
  refreshSettingsUi();
  setStatus(autoTtsEnabled ? 'Lecture automatique activée.' : 'Lecture automatique désactivée.');
});

settingsBtn.addEventListener('click', toggleSettingsPanel);

frSpeedRange.addEventListener('input', (event) => {
  ttsSettings.fr = Number(event.target.value);
  saveSettings();
  refreshSettingsUi();
  setStatus(`Vitesse FR mise à jour: ${ttsSettings.fr.toFixed(2)}x`);
});

arSpeedRange.addEventListener('input', (event) => {
  ttsSettings.ar = Number(event.target.value);
  saveSettings();
  refreshSettingsUi();
  setStatus(`Vitesse AR mise à jour: ${ttsSettings.ar.toFixed(2)}x`);
});

resetTtsSettingsBtn.addEventListener('click', () => {
  ttsSettings.fr = DEFAULT_FR_TTS_SPEED;
  ttsSettings.ar = DEFAULT_ARABIC_TTS_SPEED;
  saveSettings();
  refreshSettingsUi();
  setStatus('Vitesses TTS réinitialisées.');
});

document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-speak]');
  if (!button) return;
  playTextByChunks(button.getAttribute('data-speak') || '');
});


function warmupTtsVoices() {
  // Background warmup: loads Piper voices into Flask memory cache.
  // It does not block the UI and makes the first real TTS request much faster.
  fetch('/api/tts/warmup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ langs: ['fr', 'ar'] }),
  }).catch(() => {});
}

loadSettings();
refreshSettingsUi();
setTimeout(warmupTtsVoices, 1200);
setStatus('Prêt · TTS pipeline avec cache Piper. Ouvre Réglages pour ajuster la vitesse.');
