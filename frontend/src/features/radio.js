/**
 * Polizeifunk: radio_message als Untertitel und Sprachausgabe des Browsers.
 *
 * Zweck: macht die Entscheidungen des Dispatcher-Agenten hörbar. Gemini-TTS ist
 * gestrichen (Q0-Live-Check, Design.md "Polizeifunk-TTS"), deshalb spricht der Browser
 * selbst (speechSynthesis, de-DE, der Dispatcher funkt deutsch). Ein kurzes Rauschen davor und danach gibt den Funk-Klang.
 * Use-Cases:
 * - radio_message -> sofort hud.subtitle("Dispatch: ...")
 * - danach Vorlesen; neue Funksprüche stellen sich hinten an
 */

const RATE = 1.08;
const PITCH = 0.85;

/**
 * Kurzes Funkrauschen über WebAudio (Bandpass 300-3000 Hz).
 * @param {AudioContext|null} ac
 * @param {number} seconds
 */
function squelch(ac, seconds = 0.18) {
  if (!ac) return;
  const len = Math.floor(ac.sampleRate * seconds);
  const buf = ac.createBuffer(1, len, ac.sampleRate);
  const data = buf.getChannelData(0);
  for (let i = 0; i < len; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / len);
  const src = ac.createBufferSource();
  src.buffer = buf;
  const band = ac.createBiquadFilter();
  band.type = 'bandpass';
  band.frequency.value = 1200;
  band.Q.value = 0.7;
  const gain = ac.createGain();
  gain.gain.value = 0.25;
  src.connect(band).connect(gain).connect(ac.destination);
  src.start();
}

/**
 * Deutsche Stimme wählen (falls vorhanden).
 * @returns {SpeechSynthesisVoice|null}
 */
function pickVoice() {
  const voices = window.speechSynthesis?.getVoices() ?? [];
  return voices.find((v) => v.lang === 'de-DE') ?? voices.find((v) => v.lang?.startsWith('de')) ?? null;
}

/**
 * Feature-Einstieg: Handler für radio_message.
 * @param {import('../types.js').Ctx} ctx
 */
export function init(ctx) {
  let ac = null;
  /** AudioContext erst nach einer Nutzergeste anlegen (Autoplay-Regeln). */
  const unlock = () => {
    if (!ac) {
      try { ac = new AudioContext(); } catch { ac = null; }
    }
    window.removeEventListener('pointerdown', unlock);
    window.removeEventListener('keydown', unlock);
  };
  window.addEventListener('pointerdown', unlock);
  window.addEventListener('keydown', unlock);

  ctx.net.on('radio_message', (msg) => {
    ctx.hud.subtitle(`${msg.speaker}: ${msg.text}`, 6000);
    const synth = window.speechSynthesis;
    if (!synth) return;
    const u = new SpeechSynthesisUtterance(msg.text);
    u.lang = 'de-DE';
    u.rate = RATE;
    u.pitch = PITCH;
    const voice = pickVoice();
    if (voice) u.voice = voice;
    u.onstart = () => squelch(ac);
    u.onend = () => squelch(ac, 0.12);
    synth.speak(u);
  });
}
