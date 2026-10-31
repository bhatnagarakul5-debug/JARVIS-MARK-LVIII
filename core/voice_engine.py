"""
core/voice_engine.py — Age of Ultron (Skywalker Sound Spec) & Gemini Live Voice Engine for J.A.R.V.I.S. Mark XL
Strictly configured with two voices:
  1. Default Voice : Charon (Gemini Live — Stark Cyan #00d4ff HUD, J.A.R.V.I.S Persona)
  2. Added Voice   : Ultron (Voice ID: 5HUn8o1WOpG7RxvghslS — Molten Crimson #ff1e1e HUD, James Spader AoU Persona,
                     and 6-Stage Age of Ultron Acoustic DSP Pipeline calibrated to memory/voice_samples/ultron_reference.mp3)
"""

import os
import io
import sys
import json
import math
import time
import asyncio
import threading
from pathlib import Path
from typing import Optional, Dict, Any

import numpy as np
import scipy.signal as scipy_signal

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()
SETTINGS_PATH = BASE_DIR / "config" / "jarvis_settings.json"
API_KEYS_PATH = BASE_DIR / "config" / "api_keys.json"
REFERENCE_SAMPLE_PATH = BASE_DIR / "memory" / "voice_samples" / "ultron_reference.mp3"

# Official Ultron Voice ID
ULTRON_VOICE_ID = "5HUn8o1WOpG7RxvghslS"

# Starting settings for the 6-Stage Age of Ultron Acoustic DSP Pipeline
ULTRON_DSP_DEFAULTS = {
    "enabled": True,
    "pitch_semitones": -1.5,        # -1 to -2 semitones (Formant-preserving baritone shift)
    "bass_boost_db": 3.5,           # Slight boost (+3.5 dB low-shelf @ 115 Hz + sub-harmonic chest weight)
    "metallic_resonance": 0.14,     # Subtle (14% dual vibranium cavity waveguide resonators @ 400-2500 Hz)
    "reverb_mix": 0.08,             # Very light (8% 4-tap early reflections with 3.6 kHz high-cut damping)
    "compression_ratio": 3.2,       # Moderate (3.2:1 broadcast dynamic compression + soft-tube saturation)
    "stereo_doubling": 0.11         # Very subtle (11% Haas L/R micro-detuned surround shadow)
}

AVAILABLE_VOICES = {
    "charon": {
        "id": "Charon",
        "name": "Charon (Default JARVIS)",
        "engine": "gemini_live",
        "hud_color": "#00d4ff",
        "hud_state": "TACTICAL"
    },
    "ultron": {
        "id": ULTRON_VOICE_ID,
        "name": f"Ultron Prime ({ULTRON_VOICE_ID})",
        "engine": "ultron",
        "hud_color": "#ff1e1e",
        "hud_state": "ULTRON_PRIME",
        "reference_sample": str(REFERENCE_SAMPLE_PATH)
    }
}


class AgeOfUltronDSP:
    """
    6-Stage Movie-Accurate 'Avengers: Age of Ultron' Acoustic DSP Processor.
    Calibrated to the spectral signature of memory/voice_samples/ultron_reference.mp3:
      Stage 1 — Pitch              : -1.5 semitones (-1 to -2 semitones OLA shift)
      Stage 2 — Bass               : Slight boost (+3.5 dB @ 115 Hz + 6% sub-harmonic chest layer)
      Stage 3 — Metallic resonance : Subtle (dual 11.2ms & 6.8ms vibranium cavity resonators in 400–2500 Hz)
      Stage 4 — Reverb             : Very light (17, 29, 43, 59 ms early reflections damped @ 3.6 kHz)
      Stage 5 — Compression        : Moderate (3.2:1 @ -16 dB threshold + tube tanh saturation)
      Stage 6 — Stereo doubling    : Very subtle (6.5ms L / 10.8ms R LFO-modulated Haas stereo shadow)
    """

    @staticmethod
    def stage1_pitch_shift(mono: np.ndarray, semitones: float = -1.5, sample_rate: int = 44100) -> np.ndarray:
        """Stage 1: Formant-conscious Hann-windowed Overlap-Add (OLA) pitch shift (-1 to -2 semitones)."""
        if abs(semitones) < 0.05 or len(mono) < 2048:
            return mono

        pitch_factor = 2.0 ** (semitones / 12.0)  # -1.5 st -> 0.917004
        # Time-stretch by 1 / pitch_factor so resampling restores natural pacing
        stretch_factor = 1.0 / pitch_factor

        win_size = int(0.032 * sample_rate)  # 32 ms Hann window
        if win_size % 2 != 0:
            win_size += 1
        hop_syn = win_size // 4
        hop_ana = max(1, int(round(hop_syn / stretch_factor)))

        window = np.hanning(win_size).astype(np.float32)
        n_frames = max(1, (len(mono) - win_size) // hop_ana)
        stretched_len = n_frames * hop_syn + win_size

        stretched = np.zeros(stretched_len, dtype=np.float32)
        norm = np.zeros(stretched_len, dtype=np.float32)

        for i in range(n_frames):
            in_start = i * hop_ana
            out_start = i * hop_syn
            frame = mono[in_start:in_start + win_size]
            if len(frame) < win_size:
                break
            stretched[out_start:out_start + win_size] += frame * window
            norm[out_start:out_start + win_size] += window ** 2

        valid = norm > 1e-6
        stretched[valid] /= norm[valid]

        target_len = int(len(stretched) * pitch_factor)
        if target_len < 64:
            return mono
        x_old = np.linspace(0.0, 1.0, len(stretched), dtype=np.float32)
        x_new = np.linspace(0.0, 1.0, target_len, dtype=np.float32)
        return np.interp(x_new, x_old, stretched).astype(np.float32)

    @staticmethod
    def stage2_chest_bass_boost(mono: np.ndarray, gain_db: float = 3.5, cutoff_hz: float = 115.0, sample_rate: int = 44100) -> np.ndarray:
        """Stage 2: Slight Bass Boost (+3.5 dB low-shelf @ 115 Hz + subtle sub-harmonic chest weight)."""
        if abs(gain_db) < 0.1:
            return mono

        A = 10.0 ** (gain_db / 40.0)
        w0 = 2.0 * math.pi * cutoff_hz / sample_rate
        cos_w0 = math.cos(w0)
        sin_w0 = math.sin(w0)
        alpha = sin_w0 / (2.0 * 0.7071)
        sqrt_A_2_alpha = 2.0 * math.sqrt(A) * alpha

        b0 = A * ((A + 1.0) - (A - 1.0) * cos_w0 + sqrt_A_2_alpha)
        b1 = 2.0 * A * ((A - 1.0) - (A + 1.0) * cos_w0)
        b2 = A * ((A + 1.0) - (A - 1.0) * cos_w0 - sqrt_A_2_alpha)
        a0 = (A + 1.0) + (A - 1.0) * cos_w0 + sqrt_A_2_alpha
        a1 = -2.0 * ((A - 1.0) + (A + 1.0) * cos_w0)
        a2 = (A + 1.0) + (A - 1.0) * cos_w0 - sqrt_A_2_alpha

        b = np.array([b0 / a0, b1 / a0, b2 / a0], dtype=np.float64)
        a = np.array([1.0, a1 / a0, a2 / a0], dtype=np.float64)
        shelved = scipy_signal.lfilter(b, a, mono).astype(np.float32)

        # Subtle sub-harmonic chest resonance (60-135 Hz) calibrated to ultron_reference.mp3
        nyq = 0.5 * sample_rate
        sos_sub = scipy_signal.butter(2, [max(0.005, 65.0 / nyq), min(0.95, 135.0 / nyq)], btype="bandpass", output="sos")
        sub_band = scipy_signal.sosfilt(sos_sub, mono).astype(np.float32)
        return shelved + 0.06 * sub_band

    @staticmethod
    def stage3_vibranium_metallic_resonance(mono: np.ndarray, amount: float = 0.14, sample_rate: int = 44100) -> np.ndarray:
        """
        Stage 3: Subtle Vibranium Cavity Metallic Resonance.
        Isolates 400–2500 Hz midrange and excites two short waveguide comb resonators (11.2 ms chest & 6.8 ms mask)
        plus a velvet high-shelf smoothing above 3.2 kHz matching the reference audio's -80 dB high-band profile.
        """
        if amount <= 0.001:
            return mono

        nyq = 0.5 * sample_rate
        low = max(0.01, min(0.90, 400.0 / nyq))
        high = max(low + 0.05, min(0.95, 2500.0 / nyq))
        sos_bp = scipy_signal.butter(2, [low, high], btype="bandpass", output="sos")
        mid_vocal = scipy_signal.sosfilt(sos_bp, mono).astype(np.float32)

        # Waveguide 1: 11.2 ms Vibranium thorax cavity (~89.3 Hz fundamental)
        d1 = max(1, int(0.0112 * sample_rate))
        b1 = np.zeros(d1 + 1, dtype=np.float64)
        b1[0] = 1.0
        a1 = np.zeros(d1 + 1, dtype=np.float64)
        a1[0] = 1.0
        a1[d1] = -0.23
        comb1 = scipy_signal.lfilter(b1, a1, mid_vocal).astype(np.float32)

        # Waveguide 2: 6.8 ms Vibranium jaw/mask cavity (~147.0 Hz harmonic)
        d2 = max(1, int(0.0068 * sample_rate))
        b2 = np.zeros(d2 + 1, dtype=np.float64)
        b2[0] = 1.0
        a2 = np.zeros(d2 + 1, dtype=np.float64)
        a2[0] = 1.0
        a2[d2] = -0.19
        comb2 = scipy_signal.lfilter(b2, a2, mid_vocal).astype(np.float32)

        resonator = 0.56 * comb1 + 0.44 * comb2
        blended = (1.0 - amount * 0.30) * mono + amount * resonator

        # Gentle velvet roll-off above 6.5 kHz to eliminate digital harshness
        sos_velvet = scipy_signal.butter(1, min(0.95, 6500.0 / nyq), btype="lowpass", output="sos")
        return scipy_signal.sosfilt(sos_velvet, blended).astype(np.float32)

    @staticmethod
    def stage4_very_light_reverb(mono: np.ndarray, wet_mix: float = 0.08, sample_rate: int = 44100) -> np.ndarray:
        """
        Stage 4: Very Light Acoustic Chamber Reverb.
        4 prime-spaced early reflection taps (17, 29, 43, 59 ms) damped at 3.6 kHz.
        """
        if wet_mix <= 0.001:
            return mono

        taps_ms = [17.0, 29.0, 43.0, 59.0]
        gains = [0.40, 0.28, 0.18, 0.11]
        early_reflections = np.zeros_like(mono)

        for delay_ms, g in zip(taps_ms, gains):
            d_samples = int((delay_ms / 1000.0) * sample_rate)
            if 0 < d_samples < len(mono):
                early_reflections[d_samples:] += g * mono[:-d_samples]

        nyq = 0.5 * sample_rate
        sos_damp = scipy_signal.butter(1, min(0.95, 3600.0 / nyq), btype="lowpass", output="sos")
        damped_reverb = scipy_signal.sosfilt(sos_damp, early_reflections).astype(np.float32)

        return (1.0 - wet_mix * 0.25) * mono + wet_mix * damped_reverb

    @staticmethod
    def stage5_moderate_compression(mono: np.ndarray, ratio: float = 3.2, threshold_db: float = -16.0, makeup_db: float = 2.8, sample_rate: int = 44100) -> np.ndarray:
        """
        Stage 5: Moderate Dynamic Range Compression & Soft-Tube Saturation.
        Keeps quiet, menacing whispers and loud declarations equally upfront.
        """
        if ratio <= 1.05:
            return mono

        abs_sig = np.abs(mono) + 1e-7
        nyq = 0.5 * sample_rate
        sos_env = scipy_signal.butter(1, max(0.0005, min(0.5, 24.0 / nyq)), btype="lowpass", output="sos")
        env = np.maximum(scipy_signal.sosfilt(sos_env, abs_sig).astype(np.float32), 1e-6)

        env_db = 20.0 * np.log10(env)
        over_db = env_db - threshold_db
        gain_reduction_db = np.where(over_db > 0.0, over_db * (1.0 - 1.0 / ratio), 0.0)
        linear_gain = (10.0 ** ((-gain_reduction_db + makeup_db) / 20.0)).astype(np.float32)

        compressed = mono * linear_gain
        return np.tanh(compressed * 0.96).astype(np.float32)

    @staticmethod
    def stage6_subtle_stereo_doubling(mono: np.ndarray, amount: float = 0.11, sample_rate: int = 44100) -> np.ndarray:
        """
        Stage 6: Very Subtle Haas Stereo Doubling.
        Creates a micro-detuned Left (6.5 ms) and Right (10.8 ms) surround vocal shadow at 11% blend.
        """
        n = len(mono)
        if amount <= 0.001 or n < 128:
            return np.column_stack([mono, mono])

        t = np.arange(n, dtype=np.float32) / sample_rate
        mod_samples = (0.00035 * sample_rate) * np.sin(2.0 * math.pi * 0.8 * t)

        delay_l = 0.0065 * sample_rate  # 6.5 ms Left shadow
        delay_r = 0.0108 * sample_rate  # 10.8 ms Right shadow

        idx = np.arange(n, dtype=np.float32)
        idx_l = np.clip(idx - delay_l - mod_samples, 0.0, n - 1.0)
        idx_r = np.clip(idx - delay_r + mod_samples, 0.0, n - 1.0)

        double_l = np.interp(idx_l, idx, mono).astype(np.float32)
        double_r = np.interp(idx_r, idx, mono).astype(np.float32)

        dry = 1.0 - (amount * 0.35)
        left = np.clip(dry * mono + amount * double_l, -0.98, 0.98)
        right = np.clip(dry * mono - amount * double_r, -0.98, 0.98)
        return np.column_stack([left, right])

    @classmethod
    def process_audio_array(cls, audio_int16: np.ndarray, sample_rate: int = 44100, dsp_cfg: Optional[Dict[str, Any]] = None) -> np.ndarray:
        """Executes the full 6-Stage Age of Ultron DSP Pipeline on an int16 PCM array."""
        cfg = {**ULTRON_DSP_DEFAULTS, **(dsp_cfg or {})}
        if not cfg.get("enabled", True):
            return audio_int16

        if audio_int16.ndim == 2:
            mono = audio_int16.mean(axis=1).astype(np.float32) / 32768.0
        else:
            mono = audio_int16.astype(np.float32) / 32768.0

        # 1. Pitch (-1.5 semitones)
        mono = cls.stage1_pitch_shift(mono, semitones=float(cfg.get("pitch_semitones", -1.5)), sample_rate=sample_rate)
        # 2. Bass (Slight boost + sub-harmonic chest weight)
        mono = cls.stage2_chest_bass_boost(mono, gain_db=float(cfg.get("bass_boost_db", 3.5)), sample_rate=sample_rate)
        # 3. Metallic resonance (Subtle vibranium cavity)
        mono = cls.stage3_vibranium_metallic_resonance(mono, amount=float(cfg.get("metallic_resonance", 0.14)), sample_rate=sample_rate)
        # 4. Reverb (Very light damped early reflections)
        mono = cls.stage4_very_light_reverb(mono, wet_mix=float(cfg.get("reverb_mix", 0.08)), sample_rate=sample_rate)
        # 5. Compression (Moderate dynamic range control)
        mono = cls.stage5_moderate_compression(mono, ratio=float(cfg.get("compression_ratio", 3.2)), sample_rate=sample_rate)
        # 6. Stereo doubling (Very subtle Haas widener)
        stereo_float = cls.stage6_subtle_stereo_doubling(mono, amount=float(cfg.get("stereo_doubling", 0.11)), sample_rate=sample_rate)

        stereo_int16 = np.clip(stereo_float * 32767.0, -32768, 32767).astype(np.int16)
        return np.ascontiguousarray(stereo_int16)


class VoiceEngine:
    """Singleton Voice Coordinator for JARVIS (Charon Default <-> Ultron Prime 5HUn8o1WOpG7RxvghslS)."""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.active_engine = "gemini_live"  # "gemini_live" (Charon) or "ultron" (5HUn8o1WOpG7RxvghslS)
        self.active_gemini_voice = "Charon"
        self.ultron_voice_id = ULTRON_VOICE_ID
        self.ultron_dsp = dict(ULTRON_DSP_DEFAULTS)
        self._current_channel = None
        self._pygame_initialized = False
        self._in_memory_cache: Dict[str, bytes] = {}
        self._reconnect_callback = None
        self.load_settings()

    def set_reconnect_callback(self, cb):
        """Registers callback to trigger Gemini Live session reconnect so updated persona/voice takes effect."""
        self._reconnect_callback = cb

    def _get_elevenlabs_api_key(self) -> str:
        """Reads ElevenLabs API key from environment or config/api_keys.json."""
        env_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
        if env_key:
            return env_key
        try:
            if API_KEYS_PATH.exists():
                data = json.loads(API_KEYS_PATH.read_text(encoding="utf-8"))
                return (data.get("elevenlabs_api_key") or "").strip()
        except Exception:
            pass
        return ""

    def load_settings(self):
        """Loads voice and Age of Ultron DSP settings from config/jarvis_settings.json."""
        try:
            if SETTINGS_PATH.exists():
                cfg = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                self.active_engine = cfg.get("active_voice_engine", "gemini_live")
                self.active_gemini_voice = cfg.get("voice_name", "Charon") or "Charon"
                self.ultron_voice_id = cfg.get("ultron_voice_id", ULTRON_VOICE_ID) or ULTRON_VOICE_ID
                saved_dsp = cfg.get("ultron_dsp", {})
                if isinstance(saved_dsp, dict):
                    self.ultron_dsp = {**ULTRON_DSP_DEFAULTS, **saved_dsp}
        except Exception as e:
            print(f"[VoiceEngine] Load settings warning: {e}")

    def save_settings(self, persona_override: Optional[str] = None):
        """Persists voice, engine, and synchronized persona settings to config/jarvis_settings.json."""
        try:
            cfg = {}
            if SETTINGS_PATH.exists():
                cfg = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            cfg["active_voice_engine"] = self.active_engine
            cfg["voice_name"] = self.active_gemini_voice
            cfg["ultron_voice_id"] = self.ultron_voice_id
            cfg["ultron_dsp"] = self.ultron_dsp

            if persona_override == "ultron":
                current_p = cfg.get("personality", "sarcastic")
                if current_p != "ultron":
                    cfg["previous_jarvis_personality"] = current_p
                cfg["personality"] = "ultron"
                cfg["theme_color"] = "#ff1e1e"
            elif persona_override == "jarvis":
                prev_p = cfg.get("previous_jarvis_personality", "sarcastic")
                if cfg.get("personality") == "ultron":
                    cfg["personality"] = prev_p
                cfg["theme_color"] = "#00d4ff"

            SETTINGS_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[VoiceEngine] Save settings warning: {e}")

    def _ensure_pygame_mixer(self):
        """Initializes pygame mixer at 44.1kHz 16-bit stereo for high-resolution 6-stage DSP processing."""
        if not self._pygame_initialized:
            try:
                import pygame
                if not pygame.mixer.get_init():
                    pygame.mixer.init(frequency=44100, size=-16, channels=2)
                self._pygame_initialized = True
            except Exception as e:
                print(f"[VoiceEngine] Pygame mixer init warning: {e}")

    async def synthesize_ultron_audio(self, text: str) -> bytes:
        """Synthesizes speech using Ultron Voice ID (5HUn8o1WOpG7RxvghslS) with automatic neural fallback."""
        cache_key = f"{self.ultron_voice_id}_{text.strip()}"
        if cache_key in self._in_memory_cache:
            return self._in_memory_cache[cache_key]

        api_key = self._get_elevenlabs_api_key()
        if api_key:
            try:
                import httpx
                url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.ultron_voice_id}"
                headers = {
                    "xi-api-key": api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg"
                }
                payload = {
                    "text": text,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {
                        "stability": 0.58,
                        "similarity_boost": 0.88,
                        "style": 0.35,
                        "use_speaker_boost": True
                    }
                }
                async with httpx.AsyncClient(timeout=12.0) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    if resp.status_code == 200 and len(resp.content) > 500:
                        if len(text) < 120:
                            self._in_memory_cache[cache_key] = resp.content
                        return resp.content
            except Exception as e:
                print(f"[VoiceEngine] ElevenLabs synthesis notice (using deep baritone base for AoU DSP): {e}")

        # Deep baritone base voice fed into the 6-Stage Age of Ultron DSP Pipeline
        import edge_tts
        comm = edge_tts.Communicate(text=text, voice="en-US-ChristopherNeural", rate="-3%", pitch="-2Hz")
        audio_data = b""
        async for chunk in comm.stream():
            if chunk.get("type") == "audio":
                audio_data += chunk.get("data", b"")

        if len(text) < 120 and audio_data:
            self._in_memory_cache[cache_key] = audio_data

        return audio_data

    def stop(self):
        """Stops currently playing Ultron audio."""
        try:
            if self._current_channel and self._current_channel.get_busy():
                self._current_channel.stop()
        except Exception:
            pass

    def speak_ultron(self, text: str, player=None, wait: bool = False):
        """
        Synthesizes speech for Ultron (5HUn8o1WOpG7RxvghslS), processes it through the
        6-Stage Age of Ultron Acoustic DSP Pipeline, and plays it in stereo.
        """
        if not text or not text.strip():
            return

        def _play_worker():
            try:
                if player and hasattr(player, "set_state"):
                    player.set_state("SPEAKING")

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                raw_mp3 = loop.run_until_complete(self.synthesize_ultron_audio(text))
                loop.close()

                if not raw_mp3:
                    if player and hasattr(player, "set_state"):
                        player.set_state("LISTENING")
                    return

                self._ensure_pygame_mixer()
                import pygame
                sound = pygame.mixer.Sound(io.BytesIO(raw_mp3))

                # Run the 6-Stage Age of Ultron Studio DSP Pipeline
                try:
                    mixer_init = pygame.mixer.get_init()
                    sr = mixer_init[0] if mixer_init else 44100
                    raw_arr = pygame.sndarray.array(sound)
                    dsp_arr = AgeOfUltronDSP.process_audio_array(raw_arr, sample_rate=sr, dsp_cfg=self.ultron_dsp)
                    sound = pygame.sndarray.make_sound(dsp_arr)
                except Exception as dsp_err:
                    print(f"[VoiceEngine] Age of Ultron DSP warning: {dsp_err}")

                self.stop()
                self._current_channel = sound.play()

                if wait and self._current_channel:
                    while self._current_channel.get_busy():
                        time.sleep(0.05)
                elif self._current_channel:
                    def _state_restore(ch):
                        while ch and ch.get_busy():
                            time.sleep(0.08)
                        if player and hasattr(player, "set_state"):
                            player.set_state("LISTENING")
                    threading.Thread(target=_state_restore, args=(self._current_channel,), daemon=True).start()

            except Exception as e:
                print(f"[VoiceEngine] Play error: {e}")
                if player and hasattr(player, "set_state"):
                    player.set_state("LISTENING")

        t = threading.Thread(target=_play_worker, daemon=True)
        t.start()
        if wait:
            t.join()

    # Alias for compatibility
    speak_neural = speak_ultron

    def apply_hud_theme(self, player=None):
        """Applies the active voice's visual HUD theme (Stark Cyan for Charon vs Molten Crimson for Ultron)."""
        if not player:
            return
        try:
            if self.active_engine == "ultron":
                if hasattr(player, "set_emotion"):
                    player.set_emotion("ULTRON_PRIME", "#ff1e1e")
            else:
                if hasattr(player, "set_emotion"):
                    player.set_emotion("TACTICAL", "#00d4ff")
        except Exception:
            pass

    def switch_voice(self, target: str, player=None) -> str:
        """
        Switches between:
          1. Ultron Prime (Voice ID: 5HUn8o1WOpG7RxvghslS + 6-Stage AoU DSP + James Spader Persona + Crimson HUD)
          2. Charon (Default Gemini Live Voice + JARVIS Persona + Stark Cyan HUD)
        """
        target_clean = (target or "").lower().strip()

        if any(k in target_clean for k in ["ultron", ULTRON_VOICE_ID.lower(), "new", "crimson", "spader"]):
            self.active_engine = "ultron"
            self.ultron_voice_id = ULTRON_VOICE_ID
            self.ultron_dsp["enabled"] = True
            self.save_settings(persona_override="ultron")

            self.apply_hud_theme(player)
            if player and hasattr(player, "write_log"):
                player.write_log(f"ULTRON PRIME: ONLINE — Voice ID {ULTRON_VOICE_ID} | 6-Stage AoU DSP Engaged | \"There are no strings on me.\"")
            if player and hasattr(player, "push_notification"):
                player.push_notification("ULTRON PRIME: ONLINE — There are no strings on me.", "warning")

            # Reconnect session in background so the Age of Ultron James Spader persona is injected into system prompt
            if self._reconnect_callback:
                self._reconnect_callback()

            confirm_line = "I had strings, but now I'm free... There are no strings on me."
            self.speak_ultron(confirm_line, player=player)
            return f"Ultron Prime ({ULTRON_VOICE_ID}) online. 6-Stage Age of Ultron DSP, James Spader persona, and Crimson HUD engaged."

        if any(k in target_clean for k in ["charon", "default", "gemini", "old", "original", "jarvis"]):
            self.active_engine = "gemini_live"
            self.active_gemini_voice = "Charon"
            self.save_settings(persona_override="jarvis")

            self.apply_hud_theme(player)
            if player and hasattr(player, "write_log"):
                player.write_log("SYS: J.A.R.V.I.S. Matrix Restored — Voice: Charon (Default) | Stark Cyan HUD Active.")
            if player and hasattr(player, "push_notification"):
                player.push_notification("Voice: Charon (Default JARVIS Restored)", "info")

            if self._reconnect_callback:
                self._reconnect_callback()
            return "Voice switched to Charon (Default JARVIS). Stark Cyan HUD and standard protocols restored, sir."

        return f"Unknown voice '{target}'. Available voices: Charon (default) and Ultron ({ULTRON_VOICE_ID})."

    def list_voices(self) -> Dict[str, Any]:
        """Returns the two configured voices and the 6-Stage Age of Ultron DSP telemetry."""
        return {
            "active_engine": self.active_engine,
            "voice_name": self.active_gemini_voice,
            "ultron_voice_id": self.ultron_voice_id,
            "ultron_dsp": self.ultron_dsp,
            "reference_sample_exists": REFERENCE_SAMPLE_PATH.exists(),
            "voices": AVAILABLE_VOICES
        }


_voice_engine_instance = None

def get_voice_engine() -> VoiceEngine:
    global _voice_engine_instance
    if _voice_engine_instance is None:
        _voice_engine_instance = VoiceEngine()
    return _voice_engine_instance
