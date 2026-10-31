"""
core/voice_engine.py — Dual-Engine Voice System for J.A.R.V.I.S. Mark XL
Supports both Gemini Live prebuilt voices (Charon, Puck, Fenrir, etc.)
and High-Definition Free Microsoft Edge Neural voices (Ryan, Christopher, Thomas, Andrew, Brian).
Zero API keys needed, zero subscriptions, instant voice switching.
"""

import os
import io
import sys
import json
import time
import asyncio
import threading
from pathlib import Path
from typing import Optional, Dict, Any

# Ensure base directory resolution
def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()
SETTINGS_PATH = BASE_DIR / "config" / "jarvis_settings.json"
CACHE_DIR = BASE_DIR / "memory" / "voice_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Edge Neural Voice presets
EDGE_VOICE_PRESETS = {
    "ryan": {
        "id": "en-GB-RyanNeural",
        "name": "Ryan (MCU Jarvis)",
        "accent": "British",
        "gender": "Male",
        "description": "Calm, intellectual, composed British male voice — closest to classic MCU Jarvis.",
        "rate": "+0%",
        "pitch": "-1Hz"
    },
    "thomas": {
        "id": "en-GB-ThomasNeural",
        "name": "Thomas (Formal Butler)",
        "accent": "British",
        "gender": "Male",
        "description": "Refined, distinguished, traditional British butler tone.",
        "rate": "+0%",
        "pitch": "+0Hz"
    },
    "christopher": {
        "id": "en-US-ChristopherNeural",
        "name": "Christopher (Tactical American)",
        "accent": "American",
        "gender": "Male",
        "description": "Authoritative, deep, steady tactical commander voice.",
        "rate": "+0%",
        "pitch": "-2Hz"
    },
    "andrew": {
        "id": "en-US-AndrewMultilingualNeural",
        "name": "Andrew (Conversational Copilot)",
        "accent": "American",
        "gender": "Male",
        "description": "Warm, natural, ultra-clear modern conversational copilot.",
        "rate": "+2%",
        "pitch": "+0Hz"
    },
    "brian": {
        "id": "en-US-BrianMultilingualNeural",
        "name": "Brian (Studio Narrator)",
        "accent": "American",
        "gender": "Male",
        "description": "High-fidelity documentary studio narrator tone.",
        "rate": "+0%",
        "pitch": "+0Hz"
    },
    "sonia": {
        "id": "en-GB-SoniaNeural",
        "name": "Sonia (F.R.I.D.A.Y. Tactical)",
        "accent": "British",
        "gender": "Female",
        "description": "Crisp, energetic, military tactical female voice.",
        "rate": "+3%",
        "pitch": "+0Hz"
    }
}

# Gemini Live Voice presets
GEMINI_VOICE_PRESETS = {
    "charon": {"id": "Charon", "name": "Charon (Default Live)", "gender": "Male", "description": "Gemini Live deep, steady default voice."},
    "puck": {"id": "Puck", "name": "Puck", "gender": "Male", "description": "Gemini Live playful, energetic voice."},
    "fenrir": {"id": "Fenrir", "name": "Fenrir", "gender": "Male", "description": "Gemini Live deep, resonant voice."},
    "aoede": {"id": "Aoede", "name": "Aoede", "gender": "Female", "description": "Gemini Live elegant, balanced female voice."},
    "kore": {"id": "Kore", "name": "Kore", "gender": "Female", "description": "Gemini Live calm, soothing female voice."}
}


class VoiceEngine:
    """Singleton Dual-Engine Voice Coordinator for JARVIS."""
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
        self.rate = "+0%"
        self.pitch = "-1Hz"
        self._current_channel = None
        self._pygame_initialized = False
        self._in_memory_cache: Dict[str, bytes] = {}
        self._reconnect_callback = None
        self.load_settings()

    def set_reconnect_callback(self, cb):
        """Register callback to signal Gemini Live session when voice engine reconfig is required."""
        self._reconnect_callback = cb

    def load_settings(self):
        """Loads voice settings from config/jarvis_settings.json."""
        try:
            if SETTINGS_PATH.exists():
                cfg = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                self.active_engine = cfg.get("active_voice_engine", "gemini_live")
                self.active_gemini_voice = cfg.get("voice_name", "Charon") or "Charon"
                self.active_edge_voice = cfg.get("edge_voice", "en-GB-RyanNeural") or "en-GB-RyanNeural"
                self.rate = cfg.get("voice_rate", "+0%")
                self.pitch = cfg.get("voice_pitch", "-1Hz")
        except Exception as e:
            print(f"[VoiceEngine] Load settings warning: {e}")

    def save_settings(self):
        """Persists current voice settings to config/jarvis_settings.json without overwriting other keys."""
        try:
            cfg = {}
            if SETTINGS_PATH.exists():
                cfg = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            cfg["active_voice_engine"] = self.active_engine
            cfg["voice_name"] = self.active_gemini_voice
            cfg["edge_voice"] = self.active_edge_voice
            cfg["voice_rate"] = self.rate
            cfg["voice_pitch"] = self.pitch
            SETTINGS_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[VoiceEngine] Save settings warning: {e}")

    def _ensure_pygame_mixer(self):
        """Initializes pygame mixer safely if not already active."""
        if not self._pygame_initialized:
            try:
                import pygame
                if not pygame.mixer.get_init():
                    pygame.mixer.init()
                self._pygame_initialized = True
            except Exception as e:
                print(f"[VoiceEngine] Pygame mixer init warning: {e}")

    async def synthesize_edge_audio(self, text: str, voice_id: Optional[str] = None) -> bytes:
        """Synthesizes text using edge-tts and returns raw MP3 bytes."""
        import edge_tts

        voice = voice_id or self.active_edge_voice
        cache_key = f"{voice}_{self.rate}_{self.pitch}_{text.strip()}"
        
        # Check in-memory cache
        if cache_key in self._in_memory_cache:
            return self._in_memory_cache[cache_key]

        comm = edge_tts.Communicate(
            text=text,
            voice=voice,
            rate=self.rate,
            pitch=self.pitch
        )
        audio_data = b""
        async for chunk in comm.stream():
            if chunk.get("type") == "audio":
                audio_data += chunk.get("data", b"")

        # Cache short phrases (under 120 chars) in memory for instant reuse
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
        Synthesizes and plays text using Edge-TTS in a non-blocking background thread.
        Sets UI state to SPEAKING during playback.
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
                self.stop()
                self._current_channel = sound.play()

                if wait and self._current_channel:
                    while self._current_channel.get_busy():
                        time.sleep(0.05)
                elif self._current_channel:
                    # Non-blocking monitor to restore UI state when playback finishes
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

    def switch_voice(self, target: str, player=None) -> str:
        """
        Dynamically switches voice or engine.
        Accepts voice names: 'ryan', 'thomas', 'christopher', 'andrew', 'brian', 'charon', etc.
        or engine commands: 'neural', 'edge', 'gemini', 'live'.
        """
        target_clean = (target or "").lower().strip()

        # 1. Check for Gemini Live prebuilt voice selection
        for key, info in GEMINI_VOICE_PRESETS.items():
            if key in target_clean or info["id"].lower() == target_clean:
                self.active_engine = "gemini_live"
                self.active_gemini_voice = info["id"]
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
            if key in target_clean or info["id"].lower() in target_clean:
                self.active_engine = "edge_neural"
                self.active_edge_voice = info["id"]
                self.rate = info.get("rate", "+0%")
                self.pitch = info.get("pitch", "-1Hz")
                self.save_settings()
                msg = f"Voice switched to {info['name']} (Neural Edge-TTS Engine)."
                if player and hasattr(player, "write_log"):
                    player.write_log(f"SYS: {msg}")
                if player and hasattr(player, "push_notification"):
                    player.push_notification(f"Voice: {info['name']}", "info")
                
                # Speak confirmation in the new neural voice!
                confirm_phrase = f"Voice switched to {info['name']}, sir. Neural audio systems online and operational."
                self.speak_neural(confirm_phrase, voice_id=info["id"], player=player)
                return confirm_phrase

        # 3. Generic engine switch keywords
        if any(k in target_clean for k in ["gemini", "default", "live", "original"]):
            self.active_engine = "gemini_live"
            self.active_gemini_voice = "Charon"
            self.save_settings()
            if self._reconnect_callback:
                self._reconnect_callback()
            return "Switched back to default Gemini Live Charon voice, sir."

        if any(k in target_clean for k in ["neural", "edge", "new voice", "cloned"]):
            self.active_engine = "edge_neural"
            self.active_edge_voice = "en-GB-RyanNeural"
            self.save_settings()
            confirm_phrase = "Switched to Neural Edge-TTS Ryan voice, sir. British MCU Jarvis cadence active."
            self.speak_neural(confirm_phrase, voice_id="en-GB-RyanNeural", player=player)
            return confirm_phrase

        return f"Unknown voice '{target}'. Available neural voices: Ryan, Thomas, Christopher, Andrew, Brian. Available Gemini voices: Charon, Puck, Fenrir."

    def list_voices(self) -> Dict[str, Any]:
        """Returns structured information of all available voices across both engines."""
        return {
            "active_engine": self.active_engine,
            "active_edge_voice": self.active_edge_voice,
            "active_gemini_voice": self.active_gemini_voice,
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
