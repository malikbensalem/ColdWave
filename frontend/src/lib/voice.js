// Browser speech fallback used when ElevenLabs runs in mock mode.
export function speakMock(text, gender = "female") {
  try {
    const synth = window.speechSynthesis;
    if (!synth) return false;
    synth.cancel();
    const u = new SpeechSynthesisUtterance(text.slice(0, 300));
    const voices = synth.getVoices();
    const wantUK = voices.filter((v) => /en-GB/i.test(v.lang));
    const pool = wantUK.length ? wantUK : voices.filter((v) => /^en/i.test(v.lang));
    let pick;
    if (gender === "male") {
      pick = pool.find((v) => /male|daniel|george|arthur|oliver/i.test(v.name)) || pool[0];
    } else {
      pick = pool.find((v) => /female|amelia|kate|serena|fiona|samantha/i.test(v.name)) || pool[0];
    }
    if (pick) u.voice = pick;
    u.rate = 1; u.pitch = gender === "male" ? 0.9 : 1.05;
    synth.speak(u);
    return true;
  } catch {
    return false;
  }
}

export function stopSpeak() {
  try { window.speechSynthesis?.cancel(); } catch {}
}

// Managed HTML audio player so a single Stop control can halt real (ElevenLabs) playback.
let currentAudio = null;

export function playAudio(url, onEnded) {
  stopAudio();
  stopSpeak();
  const audio = new Audio(url);
  currentAudio = audio;
  audio.onended = () => { currentAudio = null; onEnded && onEnded(); };
  audio.onerror = () => { currentAudio = null; onEnded && onEnded(); };
  audio.play().catch(() => { currentAudio = null; onEnded && onEnded(); });
  return audio;
}

export function stopAudio() {
  if (currentAudio) {
    try { currentAudio.pause(); currentAudio.currentTime = 0; } catch {}
    currentAudio = null;
  }
}

export function stopAll() {
  stopAudio();
  stopSpeak();
}
