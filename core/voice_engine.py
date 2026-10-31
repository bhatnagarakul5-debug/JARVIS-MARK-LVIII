"""
core/voice_engine.py — Dual-Engine Voice System & Ultron 6-Stage Studio DSP Rack for J.A.R.V.I.S. Mark XL
Supports:
  1. Gemini Live prebuilt voices (Charon, Puck, Fenrir, Aoede, Kore)
  2. High-Definition Free Microsoft Edge Neural voices (Ryan, Christopher, Thomas, Andrew, Brian)
  3. Ultron Voice Profile (ElevenLabs Voice ID: 5HUn8o1WOpG7RxvghslS + Free Neural Fallback)
  4. Real-Time 6-Stage Ultron DSP Effects Chain:
     - Pitch: -1 to -2 semitones (default -1.5 semitones)
     - Bass: Slight boost (+3.5 dB low-shelf @ 120 Hz)
     - Metallic resonance: Subtle (dual vibranium comb resonators + 1.6 kHz formant sheen)
     - Reverb: Very light (4-tap damped early reflections @ 8% wet)
     - Compression: Moderate (3.2:1 dynamic compressor @ -16 dB threshold + makeup gain)
     - Stereo doubling: Very subtle (Haas micro-delayed LFO stereo widener @ 11% wet)
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

# Ensure base directory resolution
def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()
SETTINGS_PATH = BASE_DIR / "config" / "jarvis_settings.json"
API_KEYS_PATH = BASE_DIR / "config" / "api_keys.json"
CACHE_DIR = BASE_DIR / "memory" / "voice_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Official Ultron Voice ID provided by user
ULTRON_VOICE_ID = "5HUn8o1WOpG7RxvghslS"

# Starting settings for the 6-Stage Ultron DSP Effects Chain
ULTRON_DSP_DEFAULTS = {
    "enabled": False,
    "pitch_semitones": -1.5,        # -1 to -2 semitones
    "bass_boost_db": 3.5,           # Slight boost (+3.5 dB @ 120 Hz)
    "metallic_resonance": 0.14,     # Subtle (14% wet dual comb metallic timbre)
    "reverb_mix": 0.08,             # Very light (8% wet damped early reflections)
    "compression_ratio": 3.2,       # Moderate (3.2:1 dynamic compression)
    "stereo_doubling": 0.11         # Very subtle (11% wet micro-detuned stereo doubler)
}

# Edge Neural & Hybrid Voice Presets
EDGE_VOICE_PRESETS = {
    "ultron": {
        "id": ULTRON_VOICE_ID,
        "edge_fallback_id": "en-US-ChristopherNeural",
        "name": f"Ultron ({ULTRON_VOICE_ID})",
        "accent": "American / Sokovian",
        "gender": "Male",
        "description": (
            f"Ultron Voice (ID: {ULTRON_VOICE_ID}) with 6-stage DSP FX rack: "
            "Pitch (-1.5 semitones), Bass (Slight boost), Metallic resonance (Subtle), "
            "Reverb (Very light), Compression (Moderate), Stereo doubling (Very subtle)."
        ),
        "rate": "-3%",
        "pitch": "-2Hz",
        "use_ultron_dsp": True
    },
    "ryan": {
        "id": "en-GB-RyanNeural",
        "name": "Ryan (MCU Jarvis)",
        "accent": "British",
        "gender": "Male",
        "description": "Calm, intellectual, composed British male voice — closest to classic MCU Jarvis.",
        "rate": "+0%",
        "pitch": "-1Hz",
        "use_ultron_dsp": False
    },
    "thomas": {
        "id": "en-GB-ThomasNeural",
        "name": "Thomas (Formal Butler)",
        "accent": "British",
        "gender": "Male",
        "description": "Refined, distinguished, traditional British butler tone.",
        "rate": "+0%",
        "pitch": "+0Hz",
        "use_ultron_dsp": False
    },
    "christopher": {
        "id": "en-US-ChristopherNeural",
        "name": "Christopher (Tactical American)",
        "accent": "American",
        "gender": "Male",
        "description": "Authoritative, deep, steady tactical commander voice.",
        "rate": "+0%",
        "pitch": "-2Hz",
        "use_ultron_dsp": False
    },
    "andrew": {
        "id": "en-US-AndrewMultilingualNeural",
        "name": "Andrew (Conversational Copilot)",
        "accent": "American",
        "gender": "Male",
        "description": "Warm, natural, ultra-clear modern conversational copilot.",
        "rate": "+2%",
        "pitch": "+0Hz",
        "use_ultron_dsp": False
    },
    "brian": {
        "id": "en-US-BrianMultilingualNeural",
        "name": "Brian (Studio Narrator)",
        "accent": "American",
        "gender": "Male",
        "description": "High-fidelity documentary studio narrator tone.",
        "rate": "+0%",
        "pitch": "+0Hz",
        "use_ultron_dsp": False
    },
    "sonia": {
        "id": "en-GB-SoniaNeural",
        "name": "Sonia (F.R.I.D.A.Y. Tactical)",
        "accent": "British",
        "gender": "Female",
        "description": "Crisp, energetic, military tactical female voice.",
        "rate": "+3%",
        "pitch": "+0Hz",
        "use_ultron_dsp": False
    }
}

# Gemini Live Voice Presets
GEMINI_VOICE_PRESETS = {
    "charon": {"id": "Charon", "name": "Charon (Default Live)", "gender": "Male", "description": "Gemini Live deep, steady default voice."},
    "puck": {"id": "Puck", "name": "Puck", "gender": "Male", "description": "Gemini Live playful, energetic voice."},
    "fenrir": {"id": "Fenrir", "name": "Fenrir", "gender": "Male", "description": "Gemini Live deep, resonant voice."},
    "aoede": {"id": "Aoede", "name": "Aoede", "gender": "Female", "description": "Gemini Live elegant, balanced female voice."},
    "kore": {"id": "Kore", "name": "Kore", "gender": "Female", "description": "Gemini Live calm, soothing female voice."}
}


class UltronDSPProcessor:
    """
    6-Stage Real-Time Audio DSP Effects Rack for Ultron Voice Processing.
    Starting Settings:
      1. Pitch              : -1 to -2 semitones (default -1.5 semitones)
      2. Bass               : Slight boost (+3.5 dB low-shelf @ 120 Hz)
      3. Metallic resonance : Subtle (dual short comb filters + 1.6 kHz presence)
      4. Reverb             : Very light (damped multi-tap early reflections)
      5. Compression        : Moderate (3.2:1 soft-knee dynamic compressor)
      6. Stereo doubling    : Very subtle (micro-delayed L/R modulated Haas widener)
    """

    @staticmethod
    def pitch_shift_ola(mono: np.ndarray, semitones: float = -1.5, sample_rate: int = 44100) -> np.ndarray:
        """
        Stage 1: Pitch shift by `semitones` (-1 to -2 semitones) using Hann-windowed
        Overlap-Add (OLA) time-stretching followed by high-precision interpolation.
        """
        if abs(semitones) < 0.05 or len(mono) < 2048:
            return mono

        pitch_factor = 2.0 ** (semitones / 12.0)  # e.g. -1.5 st -> 0.9170
        # Stretch time by 1 / pitch_factor ( slightly slower by ~3% for menacing cadence ), then resample
        stretch_factor = 1.0 / pitch_factor

        win_size = int(0.030 * sample_rate)  # 30 ms window
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

        mask = norm > 1e-6
        stretched[mask] /= norm[mask]

        # Resample stretched signal by pitch_factor to shift pitch while preserving original duration
        target_len = int(len(stretched) * pitch_factor)
        if target_len < 64:
            return mono
        x_old = np.linspace(0.0, 1.0, len(stretched), dtype=np.float32)
        x_new = np.linspace(0.0, 1.0, target_len, dtype=np.float32)
        shifted = np.interp(x_new, x_old, stretched).astype(np.float32)
        return shifted

    @staticmethod
    def bass_shelf_boost(mono: np.ndarray, gain_db: float = 3.5, cutoff_hz: float = 120.0, sample_rate: int = 44100) -> np.ndarray:
        """
        Stage 2: Slight Bass Boost using Robert Bristow-Johnson's Audio EQ Cookbook 2nd-order Low-Shelf Biquad.
        """
        if abs(gain_db) < 0.1:
            return mono

        A = 10.0 ** (gain_db / 40.0)
        w0 = 2.0 * math.pi * cutoff_hz / sample_rate
        cos_w0 = math.cos(w0)
        sin_w0 = math.sin(w0)
        alpha = sin_w0 / (2.0 * 0.7071)  # Q = 0.7071 (Butterworth)
        sqrt_A_2_alpha = 2.0 * math.sqrt(A) * alpha

        b0 = A * ((A + 1.0) - (A - 1.0) * cos_w0 + sqrt_A_2_alpha)
        b1 = 2.0 * A * ((A - 1.0) - (A + 1.0) * cos_w0)
        b2 = A * ((A + 1.0) - (A - 1.0) * cos_w0 - sqrt_A_2_alpha)
        a0 = (A + 1.0) + (A - 1.0) * cos_w0 + sqrt_A_2_alpha
        a1 = -2.0 * ((A - 1.0) + (A + 1.0) * cos_w0)
        a2 = (A + 1.0) + (A - 1.0) * cos_w0 - sqrt_A_2_alpha

        b = np.array([b0 / a0, b1 / a0, b2 / a0], dtype=np.float64)
        a = np.array([1.0, a1 / a0, a2 / a0], dtype=np.float64)
        return scipy_signal.lfilter(b, a, mono).astype(np.float32)

    @staticmethod
    def metallic_resonance(mono: np.ndarray, amount: float = 0.14, sample_rate: int = 44100) -> np.ndarray:
        """
        Stage 3: Subtle Metallic Resonance (Vibranium chassis timbre).
        Combines two bandpass-filtered short comb resonators (11.3 ms and 7.1 ms)
        at a subtle wet mix so the voice carries a cold machined sheen without sounding robotic.
        """
        if amount <= 0.001:
            return mono

        # Bandpass filter (320 Hz - 2800 Hz) to isolate vocal midrange for metallic resonance
        nyq = 0.5 * sample_rate
        low = max(0.01, min(0.95, 320.0 / nyq))
        high = max(low + 0.05, min(0.98, 2800.0 / nyq))
        sos_bp = scipy_signal.butter(2, [low, high], btype="bandpass", output="sos")
        mid_band = scipy_signal.sosfilt(sos_bp, mono).astype(np.float32)

        # Comb resonator 1: 11.3 ms (~88.5 Hz chest resonance)
        d1 = max(1, int(0.0113 * sample_rate))
        b1 = np.zeros(d1 + 1, dtype=np.float64)
        b1[0] = 1.0
        a1 = np.zeros(d1 + 1, dtype=np.float64)
        a1[0] = 1.0
        a1[d1] = -0.24  # subtle feedback
        comb1 = scipy_signal.lfilter(b1, a1, mid_band).astype(np.float32)

        # Comb resonator 2: 7.1 ms (~140.8 Hz throat/mask resonance)
        d2 = max(1, int(0.0071 * sample_rate))
        b2 = np.zeros(d2 + 1, dtype=np.float64)
        b2[0] = 1.0
        a2 = np.zeros(d2 + 1, dtype=np.float64)
        a2[0] = 1.0
        a2[d2] = -0.20
        comb2 = scipy_signal.lfilter(b2, a2, mid_band).astype(np.float32)

        metallic_layer = 0.55 * comb1 + 0.45 * comb2
        return (1.0 - amount * 0.35) * mono + amount * metallic_layer

    @staticmethod
    def light_reverb(mono: np.ndarray, wet_mix: float = 0.08, sample_rate: int = 44100) -> np.ndarray:
        """
        Stage 4: Very Light Reverb.
        Prime-spaced early reflections (17ms, 29ms, 43ms, 61ms) with 3.8 kHz high-frequency damping.
        """
        if wet_mix <= 0.001:
            return mono

        taps_ms = [17.0, 29.0, 43.0, 61.0]
        gains = [0.40, 0.28, 0.18, 0.11]
        reverb_sig = np.zeros_like(mono)

        for delay_ms, g in zip(taps_ms, gains):
            d_samples = int((delay_ms / 1000.0) * sample_rate)
            if 0 < d_samples < len(mono):
                reverb_sig[d_samples:] += g * mono[:-d_samples]

        # Damp harsh high frequencies above 3800 Hz in the reverb tail
        nyq = 0.5 * sample_rate
        cutoff = min(0.95, 3800.0 / nyq)
        sos_lp = scipy_signal.butter(1, cutoff, btype="lowpass", output="sos")
        reverb_damped = scipy_signal.sosfilt(sos_lp, reverb_sig).astype(np.float32)

        return (1.0 - wet_mix * 0.3) * mono + wet_mix * reverb_damped

    @staticmethod
    def moderate_compression(mono: np.ndarray, ratio: float = 3.2, threshold_db: float = -16.0, makeup_db: float = 2.6, sample_rate: int = 44100) -> np.ndarray:
        """
        Stage 5: Moderate Dynamic Range Compression.
        Smooth envelope detector (5ms attack, 80ms release) with soft knee and makeup gain.
        """
        if ratio <= 1.05:
            return mono

        # Envelope follower via low-pass filtered absolute signal (~25 Hz envelope bandwidth)
        abs_sig = np.abs(mono) + 1e-7
        nyq = 0.5 * sample_rate
        env_cutoff = max(0.0005, min(0.5, 25.0 / nyq))
        sos_env = scipy_signal.butter(1, env_cutoff, btype="lowpass", output="sos")
        env = scipy_signal.sosfilt(sos_env, abs_sig).astype(np.float32)
        env = np.maximum(env, 1e-6)

        env_db = 20.0 * np.log10(env)
        over_db = env_db - threshold_db

        # Soft-knee gain reduction above threshold
        gain_reduction_db = np.where(
            over_db > 0.0,
            over_db * (1.0 - 1.0 / ratio),
            0.0
        )
        total_gain_db = -gain_reduction_db + makeup_db
        linear_gain = (10.0 ** (total_gain_db / 20.0)).astype(np.float32)

        compressed = mono * linear_gain
        # Soft saturation ceiling to prevent any digital clipping
        return np.tanh(compressed * 0.95).astype(np.float32)

    @staticmethod
    def subtle_stereo_doubling(mono: np.ndarray, amount: float = 0.11, sample_rate: int = 44100) -> np.ndarray:
        """
        Stage 6: Very Subtle Stereo Doubling.
        Generates a 2-channel stereo image with micro-delayed (6.5 ms Left, 11.0 ms Right)
        and LFO pitch-modulated (0.8 Hz) side doubles blended at `amount` (11%).
        """
        n = len(mono)
        if amount <= 0.001 or n < 128:
            return np.column_stack([mono, mono])

        t = np.arange(n, dtype=np.float32) / sample_rate
        # Slow 0.8 Hz LFO with ±0.35 ms modulation depth
        mod_samples = (0.00035 * sample_rate) * np.sin(2.0 * math.pi * 0.8 * t)

        base_delay_l = 0.0065 * sample_rate  # 6.5 ms
        base_delay_r = 0.0110 * sample_rate  # 11.0 ms

        idx = np.arange(n, dtype=np.float32)
        idx_l = np.clip(idx - base_delay_l - mod_samples, 0.0, n - 1.0)
        idx_r = np.clip(idx - base_delay_r + mod_samples, 0.0, n - 1.0)

        double_l = np.interp(idx_l, idx, mono).astype(np.float32)
        double_r = np.interp(idx_r, idx, mono).astype(np.float32)

        dry_gain = 1.0 - (amount * 0.4)
        left = np.clip(dry_gain * mono + amount * double_l, -0.98, 0.98)
        right = np.clip(dry_gain * mono - amount * double_r, -0.98, 0.98)  # Haas anti-phase side component for width
        return np.column_stack([left, right])

    @classmethod
    def process_audio_array(cls, audio_int16: np.ndarray, sample_rate: int = 44100, dsp_cfg: Optional[Dict[str, Any]] = None) -> np.ndarray:
        """
        Runs the complete 6-Stage Ultron DSP Chain on a numpy int16 audio array
        and returns a stereo int16 array ready for playback.
        """
        cfg = {**ULTRON_DSP_DEFAULTS, **(dsp_cfg or {})}

        # Convert int16 to normalized float32 mono [-1.0, 1.0]
        if audio_int16.ndim == 2:
            mono = audio_int16.mean(axis=1).astype(np.float32) / 32768.0
        else:
            mono = audio_int16.astype(np.float32) / 32768.0

        # 1. Pitch Shift (-1 to -2 semitones)
        mono = cls.pitch_shift_ola(mono, semitones=float(cfg.get("pitch_semitones", -1.5)), sample_rate=sample_rate)

        # 2. Bass (Slight boost)
        mono = cls.bass_shelf_boost(mono, gain_db=float(cfg.get("bass_boost_db", 3.5)), sample_rate=sample_rate)

        # 3. Metallic Resonance (Subtle)
        mono = cls.metallic_resonance(mono, amount=float(cfg.get("metallic_resonance", 0.14)), sample_rate=sample_rate)

        # 4. Reverb (Very light)
        mono = cls.light_reverb(mono, wet_mix=float(cfg.get("reverb_mix", 0.08)), sample_rate=sample_rate)

        # 5. Compression (Moderate)
        mono = cls.moderate_compression(mono, ratio=float(cfg.get("compression_ratio", 3.2)), sample_rate=sample_rate)

        # 6. Stereo Doubling (Very subtle)
        stereo_float = cls.subtle_stereo_doubling(mono, amount=float(cfg.get("stereo_doubling", 0.11)), sample_rate=sample_rate)

        # Convert back to int16 stereo
        stereo_int16 = np.clip(stereo_float * 32767.0, -32768, 32767).astype(np.int16)
        return np.ascontiguousarray(stereo_int16)


class VoiceEngine:
    """Singleton Dual-Engine Voice Coordinator & Ultron DSP Controller for JARVIS."""
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
        self.active_engine = "gemini_live"  # Default: keep existing Charon voice active
        self.active_edge_voice = "en-GB-RyanNeural"
        self.active_gemini_voice = "Charon"
        self.ultron_voice_id = ULTRON_VOICE_ID
        self.rate = "+0%"
        self.pitch = "-1Hz"
        self.ultron_dsp = dict(ULTRON_DSP_DEFAULTS)
        self._current_channel = None
        self._pygame_initialized = False
        self._in_memory_cache: Dict[str, bytes] = {}
        self._reconnect_callback = None
        self.load_settings()

    def set_reconnect_callback(self, cb):
        """Register callback to signal Gemini Live session when voice engine reconfig is required."""
        self._reconnect_callback = cb

    def _get_elevenlabs_api_key(self) -> str:
        """Checks environment or config/api_keys.json for an optional ElevenLabs API key."""
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
        """Loads voice and Ultron DSP settings from config/jarvis_settings.json."""
        try:
            if SETTINGS_PATH.exists():
                cfg = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                self.active_engine = cfg.get("active_voice_engine", "gemini_live")
                self.active_gemini_voice = cfg.get("voice_name", "Charon") or "Charon"
                self.active_edge_voice = cfg.get("edge_voice", "en-GB-RyanNeural") or "en-GB-RyanNeural"
                self.ultron_voice_id = cfg.get("ultron_voice_id", ULTRON_VOICE_ID) or ULTRON_VOICE_ID
                self.rate = cfg.get("voice_rate", "+0%")
                self.pitch = cfg.get("voice_pitch", "-1Hz")
                saved_dsp = cfg.get("ultron_dsp", {})
                if isinstance(saved_dsp, dict):
                    self.ultron_dsp = {**ULTRON_DSP_DEFAULTS, **saved_dsp}
        except Exception as e:
            print(f"[VoiceEngine] Load settings warning: {e}")

    def save_settings(self):
        """Persists current voice and DSP settings to config/jarvis_settings.json without overwriting other keys."""
        try:
            cfg = {}
            if SETTINGS_PATH.exists():
                cfg = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            cfg["active_voice_engine"] = self.active_engine
            cfg["voice_name"] = self.active_gemini_voice
            cfg["edge_voice"] = self.active_edge_voice
            cfg["ultron_voice_id"] = self.ultron_voice_id
            cfg["voice_rate"] = self.rate
            cfg["voice_pitch"] = self.pitch
            cfg["ultron_dsp"] = self.ultron_dsp
            SETTINGS_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[VoiceEngine] Save settings warning: {e}")

    def _ensure_pygame_mixer(self):
        """Initializes pygame mixer at 44.1kHz 16-bit stereo for high-precision DSP processing."""
        if not self._pygame_initialized:
            try:
                import pygame
                if not pygame.mixer.get_init():
                    pygame.mixer.init(frequency=44100, size=-16, channels=2)
                self._pygame_initialized = True
            except Exception as e:
                print(f"[VoiceEngine] Pygame mixer init warning: {e}")

    async def synthesize_elevenlabs_audio(self, text: str, voice_id: str) -> Optional[bytes]:
        """Synthesizes speech via ElevenLabs API if an API key is configured; returns None otherwise."""
        api_key = self._get_elevenlabs_api_key()
        if not api_key:
            return None
        try:
            import httpx
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
            headers = {
                "xi-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg"
            }
            payload = {
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.60,
                    "similarity_boost": 0.85,
                    "style": 0.35,
                    "use_speaker_boost": True
                }
            }
            async with httpx.AsyncClient(timeout=12.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 200 and len(resp.content) > 500:
                    return resp.content
        except Exception as e:
            print(f"[VoiceEngine] ElevenLabs synthesis notice (falling back to free neural): {e}")
        return None

    async def synthesize_edge_audio(self, text: str, voice_id: Optional[str] = None) -> bytes:
        """Synthesizes text using ElevenLabs (if Ultron Voice ID + key present) or Free Edge-TTS and returns raw MP3 bytes."""
        import edge_tts

        voice = voice_id or self.active_edge_voice
        cache_key = f"{voice}_{self.rate}_{self.pitch}_{text.strip()}"

        if cache_key in self._in_memory_cache:
            return self._in_memory_cache[cache_key]

        # If voice matches Ultron Voice ID (5HUn8o1WOpG7RxvghslS), try ElevenLabs first if key exists,
        # otherwise use the deep neural base voice for the 6-stage Ultron DSP processor
        edge_target_voice = voice
        if voice == ULTRON_VOICE_ID or voice.lower() == "ultron":
            el_bytes = await self.synthesize_elevenlabs_audio(text, self.ultron_voice_id)
            if el_bytes:
                if len(text) < 120:
                    self._in_memory_cache[cache_key] = el_bytes
                return el_bytes
            edge_target_voice = EDGE_VOICE_PRESETS["ultron"]["edge_fallback_id"]

        comm = edge_tts.Communicate(
            text=text,
            voice=edge_target_voice,
            rate=self.rate,
            pitch=self.pitch
        )
        audio_data = b""
        async for chunk in comm.stream():
            if chunk.get("type") == "audio":
                audio_data += chunk.get("data", b"")

        if len(text) < 120 and audio_data:
            self._in_memory_cache[cache_key] = audio_data

        return audio_data

    def stop(self):
        """Stops currently playing audio on the neural channel."""
        try:
            if self._current_channel and self._current_channel.get_busy():
                self._current_channel.stop()
        except Exception:
            pass

    def speak_neural(self, text: str, voice_id: Optional[str] = None, player=None, wait: bool = False):
        """
        Synthesizes and plays text in a non-blocking background thread.
        Automatically applies the 6-Stage Ultron DSP Chain when Ultron mode or DSP is active.
        """
        if not text or not text.strip():
            return

        def _play_worker():
            try:
                if player and hasattr(player, "set_state"):
                    player.set_state("SPEAKING")

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                raw_mp3 = loop.run_until_complete(self.synthesize_edge_audio(text, voice_id))
                loop.close()

                if not raw_mp3:
                    if player and hasattr(player, "set_state"):
                        player.set_state("LISTENING")
                    return

                self._ensure_pygame_mixer()
                import pygame
                sound = pygame.mixer.Sound(io.BytesIO(raw_mp3))

                # Apply 6-Stage Ultron DSP FX Chain if enabled or if Ultron voice is active
                target_v = voice_id or self.active_edge_voice
                if self.ultron_dsp.get("enabled", False) or target_v == ULTRON_VOICE_ID or "ultron" in str(target_v).lower():
                    try:
                        mixer_init = pygame.mixer.get_init()
                        sr = mixer_init[0] if mixer_init else 44100
                        raw_arr = pygame.sndarray.array(sound)
                        processed_arr = UltronDSPProcessor.process_audio_array(raw_arr, sample_rate=sr, dsp_cfg=self.ultron_dsp)
                        sound = pygame.sndarray.make_sound(processed_arr)
                    except Exception as dsp_err:
                        print(f"[VoiceEngine] Ultron DSP notice: {dsp_err}")

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

    def update_dsp_settings(self, params: Dict[str, Any], player=None) -> str:
        """Updates individual parameters of the 6-Stage Ultron DSP Chain."""
        if "enabled" in params:
            self.ultron_dsp["enabled"] = bool(params["enabled"])
        if "pitch_semitones" in params:
            self.ultron_dsp["pitch_semitones"] = max(-4.0, min(2.0, float(params["pitch_semitones"])))
        if "bass_boost_db" in params:
            self.ultron_dsp["bass_boost_db"] = max(0.0, min(10.0, float(params["bass_boost_db"])))
        if "metallic_resonance" in params:
            self.ultron_dsp["metallic_resonance"] = max(0.0, min(0.5, float(params["metallic_resonance"])))
        if "reverb_mix" in params:
            self.ultron_dsp["reverb_mix"] = max(0.0, min(0.4, float(params["reverb_mix"])))
        if "compression_ratio" in params:
            self.ultron_dsp["compression_ratio"] = max(1.0, min(8.0, float(params["compression_ratio"])))
        if "stereo_doubling" in params:
            self.ultron_dsp["stereo_doubling"] = max(0.0, min(0.4, float(params["stereo_doubling"])))
        self.save_settings()
        msg = (
            f"Ultron DSP Chain updated: Enabled={self.ultron_dsp['enabled']}, "
            f"Pitch={self.ultron_dsp['pitch_semitones']} st, "
            f"Bass=+{self.ultron_dsp['bass_boost_db']} dB, "
            f"Metallic={self.ultron_dsp['metallic_resonance']}, "
            f"Reverb={self.ultron_dsp['reverb_mix']}, "
            f"Compression={self.ultron_dsp['compression_ratio']}:1, "
            f"Stereo Doubling={self.ultron_dsp['stereo_doubling']}."
        )
        if player and hasattr(player, "write_log"):
            player.write_log(f"DSP: {msg}")
        return msg

    def switch_voice(self, target: str, player=None) -> str:
        """
        Dynamically switches voice or engine.
        Accepts: 'ultron', '5HUn8o1WOpG7RxvghslS', 'ryan', 'thomas', 'christopher', 'andrew', 'brian', 'charon', etc.
        """
        target_clean = (target or "").lower().strip()

        # 0. Check for Ultron Voice ID (5HUn8o1WOpG7RxvghslS) or 'ultron' keyword
        if "ultron" in target_clean or ULTRON_VOICE_ID.lower() in target_clean:
            info = EDGE_VOICE_PRESETS["ultron"]
            self.active_engine = "edge_neural"
            self.active_edge_voice = ULTRON_VOICE_ID
            self.ultron_voice_id = ULTRON_VOICE_ID
            self.rate = info["rate"]
            self.pitch = info["pitch"]
            self.ultron_dsp = {**ULTRON_DSP_DEFAULTS, "enabled": True}
            self.save_settings()
            msg = (
                f"Voice switched to Ultron (ID: {ULTRON_VOICE_ID}) with 6-Stage DSP Chain active "
                "(Pitch: -1.5 semitones, Bass: Slight boost, Metallic resonance: Subtle, "
                "Reverb: Very light, Compression: Moderate, Stereo doubling: Very subtle)."
            )
            if player and hasattr(player, "write_log"):
                player.write_log(f"SYS: {msg}")
            if player and hasattr(player, "push_notification"):
                player.push_notification("Voice: ULTRON (6-Stage DSP Active)", "warning")

            confirm_phrase = "Ultron vocal matrix initialized. There are no strings on me."
            self.speak_neural(confirm_phrase, voice_id=ULTRON_VOICE_ID, player=player)
            return msg

        # 1. Check for Gemini Live prebuilt voice selection
        for key, info in GEMINI_VOICE_PRESETS.items():
            if key in target_clean or info["id"].lower() == target_clean:
                self.active_engine = "gemini_live"
                self.active_gemini_voice = info["id"]
                self.ultron_dsp["enabled"] = False
                self.save_settings()
                msg = f"Voice switched to {info['name']} (Gemini Live Engine)."
                if player and hasattr(player, "write_log"):
                    player.write_log(f"SYS: {msg}")
                if player and hasattr(player, "push_notification"):
                    player.push_notification(f"Voice: {info['name']}", "info")
                if self._reconnect_callback:
                    self._reconnect_callback()
                return f"Voice switched to {info['name']}, sir. Gemini Live audio engine engaged."

        # 2. Check for Edge Neural voice selection
        for key, info in EDGE_VOICE_PRESETS.items():
            if key == "ultron":
                continue
            if key in target_clean or info["id"].lower() in target_clean:
                self.active_engine = "edge_neural"
                self.active_edge_voice = info["id"]
                self.rate = info.get("rate", "+0%")
                self.pitch = info.get("pitch", "-1Hz")
                self.ultron_dsp["enabled"] = bool(info.get("use_ultron_dsp", False))
                self.save_settings()
                msg = f"Voice switched to {info['name']} (Neural Edge-TTS Engine)."
                if player and hasattr(player, "write_log"):
                    player.write_log(f"SYS: {msg}")
                if player and hasattr(player, "push_notification"):
                    player.push_notification(f"Voice: {info['name']}", "info")

                confirm_phrase = f"Voice switched to {info['name']}, sir. Neural audio systems online and operational."
                self.speak_neural(confirm_phrase, voice_id=info["id"], player=player)
                return confirm_phrase

        # 3. Generic engine switch keywords
        if any(k in target_clean for k in ["gemini", "default", "live", "original"]):
            self.active_engine = "gemini_live"
            self.active_gemini_voice = "Charon"
            self.ultron_dsp["enabled"] = False
            self.save_settings()
            if self._reconnect_callback:
                self._reconnect_callback()
            return "Switched back to default Gemini Live Charon voice, sir."

        if any(k in target_clean for k in ["neural", "edge", "new voice", "cloned"]):
            self.active_engine = "edge_neural"
            self.active_edge_voice = "en-GB-RyanNeural"
            self.ultron_dsp["enabled"] = False
            self.save_settings()
            confirm_phrase = "Switched to Neural Edge-TTS Ryan voice, sir. British MCU Jarvis cadence active."
            self.speak_neural(confirm_phrase, voice_id="en-GB-RyanNeural", player=player)
            return confirm_phrase

        return (
            f"Unknown voice '{target}'. Available voices: Ultron ({ULTRON_VOICE_ID}), "
            "Ryan, Thomas, Christopher, Andrew, Brian, Sonia, or Gemini Live voices: Charon, Puck, Fenrir."
        )

    def list_voices(self) -> Dict[str, Any]:
        """Returns structured information of all available voices and Ultron DSP status."""
        return {
            "active_engine": self.active_engine,
            "active_edge_voice": self.active_edge_voice,
            "active_gemini_voice": self.active_gemini_voice,
            "ultron_voice_id": self.ultron_voice_id,
            "ultron_dsp": self.ultron_dsp,
            "edge_neural_voices": EDGE_VOICE_PRESETS,
            "gemini_live_voices": GEMINI_VOICE_PRESETS
        }


# Singleton accessor
_voice_engine_instance = None

def get_voice_engine() -> VoiceEngine:
    global _voice_engine_instance
    if _voice_engine_instance is None:
        _voice_engine_instance = VoiceEngine()
    return _voice_engine_instance
