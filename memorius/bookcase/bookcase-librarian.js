/* bookcase-librarian.js — Web Speech API voice guidance for the vault
 * bookcase (output + optional hold-to-talk input). No TTS service, no API
 * keys, no model downloads. Unavailable environments degrade to text-only:
 * say() always renders the guidance line via onLog. Voice choice persists
 * in localStorage under "bc-voice".
 */

const LS_KEY = "bc-voice";
/* Heuristic for a calm, professional default voice (spec preference rule;
   falls back to first English voice, then first available voice). */
const CALM_VOICE = /female|serena|samantha|jenny|aria|moira|zira|guy|daniel|neuma|google (uk|us) english/i;

export class Librarian {
  constructor({ onLog = () => {} } = {}) {
    this.onLog = onLog;
    this.enabled = true;
    this.voices = [];
    this.voice = null;
    this._supported = typeof window !== "undefined" && "speechSynthesis" in window;
    this._rec = null;
    if (this._supported) {
      const load = () => {
        this.voices = window.speechSynthesis.getVoices();
        if (!this.voices.length) return;
        const uri = safeGet(LS_KEY);
        this.voice = this.voices.find((v) => v.voiceURI === uri) || this._pickDefault();
      };
      load();
      window.speechSynthesis.onvoiceschanged = load;
    }
  }

  get supported() {
    return this._supported;
  }

  _pickDefault() {
    if (!this.voices.length) return null;
    return (
      this.voices.find((v) => v.default && CALM_VOICE.test(v.name)) ||
      this.voices.find((v) => CALM_VOICE.test(v.name)) ||
      this.voices.find((v) => v.lang && v.lang.startsWith("en")) ||
      this.voices[0]
    );
  }

  setVoiceByUri(uri) {
    const match = this.voices.find((v) => v.voiceURI === uri);
    if (!match) return false;
    this.voice = match;
    try {
      localStorage.setItem(LS_KEY, uri);
    } catch {
      /* private mode — non-fatal */
    }
    return true;
  }

  /** Speak (when enabled) and always log the text so guidance stays visible. */
  say(text, { log = true, interrupt = true } = {}) {
    if (log) this.onLog(text);
    if (this.enabled && this._supported && this.voices.length) {
      try {
        // a librarian answers the latest question, not a queue of old ones
        if (interrupt) window.speechSynthesis.cancel();
        const u = new SpeechSynthesisUtterance(text);
        if (this.voice) {
          u.voice = this.voice;
          u.lang = this.voice.lang;
        }
        u.rate = 0.95;
        u.pitch = 1.0;
        window.speechSynthesis.speak(u);
      } catch {
        /* text-only fallback */
      }
    }
  }

  greet(bookCount, shelfCount) {
    this.say(
      `Good evening. This library holds ${bookCount} books across ${shelfCount} shelves. ` +
      "Tell me what you are looking for, and follow my lantern."
    );
  }

  announceVault(name, bookCount) {
    this.say(`Now showing vault ${name}. ${bookCount} books on the shelves.`);
  }

  /* directions: spoken-direction hint for the top hit (from scene.describe). */
  announceSearch(query, results, directions = null) {
    if (!results.length) {
      this.say(`No matches for "${query}". Try a different word, or ask me about something broader.`);
      return;
    }
    const where = (r) => `shelf ${r.shelf || "default"}, folder ${r.folder || "default"}`;
    const name = (r) => r.label || r.note || r.id;
    let msg = `${results.length} match${results.length === 1 ? "" : "es"} for "${query}". `;
    msg += `Top hit: "${name(results[0])}" on ${where(results[0])}`;
    msg += directions ? `, ${directions.text}. Follow the lantern. ` : ". ";
    for (const r of results.slice(1, 3)) msg += `Also: "${name(r)}" on ${where(r)}. `;
    this.say(msg);
  }

  /* Cycling through results with N / P. */
  announceStep(index, total, result, directions = null) {
    const name = result.label || result.note || result.id;
    this.say(`Result ${index + 1} of ${total}: "${name}"${directions ? `, ${directions.text}` : ""}.`);
  }

  /* Read a book's opening lines aloud (voice only; text is already on screen). */
  readAloud(title, content) {
    const body = String(content || "").replace(/\s+/g, " ").slice(0, 600);
    this.onLog(`Reading "${title}" aloud.`);
    this.say(`${title}. ${body}`, { log: false });
  }

  hush() {
    if (this._supported) {
      try {
        window.speechSynthesis.cancel();
      } catch {
        /* nothing to stop */
      }
    }
  }

  announceError(message) {
    this.say(message);
  }

  /* ── hold-to-talk (Chromium only) ─────────────────────────── */
  get talkSupported() {
    return typeof window !== "undefined" && !!(
      window.SpeechRecognition || window.webkitSpeechRecognition
    );
  }

  startTalk(onFinal) {
    if (!this.talkSupported) return false;
    const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
    this._rec = new Ctor();
    this._rec.lang = "en-US";
    this._rec.interimResults = false;
    this._rec.maxAlternatives = 1;
    this._rec.onresult = (e) => {
      const t = e.results[0] && e.results[0][0] && e.results[0][0].transcript;
      if (t) onFinal(t);
    };
    try {
      this._rec.start();
      return true;
    } catch {
      this._rec = null;
      return false;
    }
  }

  stopTalk() {
    if (this._rec) {
      try {
        this._rec.stop();
      } catch {
        /* already stopped */
      }
      this._rec = null;
    }
  }
}

function safeGet(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
