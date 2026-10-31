"""
core/voice_engine.py — Voice Engine for J.A.R.V.I.S. Mark XL
Supports:
  1. Default Voice: Charon (Gemini Live)
  2. Added Voice: Ultron (Voice ID: 5HUn8o1WOpG7RxvghslS)
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

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()
SETTINGS_PATH = BASE_DIR / "config" / "jarvis_settings.json"
API_KEYS_PATH = BASE_DIR / "config" / "api_keys.json"

# Official Ultron Voice ID
ULTRON_VOICE_ID = "5HUn8o1WOpG7RxvghslS"

AVAILABLE_VOICES = {
    "charon": {
        "id": "Charon",
        "name": "Charon (Default)",
        "engine": "gemini_live"
    },
    "ultron": {
        "id": ULTRON_VOICE_ID,
        "name": f"Ultron ({ULTRON_VOICE_ID})",
        "engine": "ultron"
    }
}


class VoiceEngine:
    """Singleton Voice Coordinator for JARVIS (Charon + Ultron 5HUn8o1WOpG7RxvghslS)."""
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
        self._current_channel = None
        self._pygame_initialized = False
        self._in_memory_cache: Dict[str, bytes] = {}
        self._reconnect_callback = None
        self.load_settings()

    def set_reconnect_callback(self, cb):
        """Register callback to signal Gemini Live session when voice engine reconfig is required."""
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
        """Loads voice settings from config/jarvis_settings.json."""
        try:
            if SETTINGS_PATH.exists():
                cfg = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                self.active_engine = cfg.get("active_voice_engine", "gemini_live")
                self.active_gemini_voice = cfg.get("voice_name", "Charon") or "Charon"
                self.ultron_voice_id = cfg.get("ultron_voice_id", ULTRON_VOICE_ID) or ULTRON_VOICE_ID
        except Exception as e:
            print(f"[VoiceEngine] Load settings warning: {e}")

    def save_settings(self):
        """Persists current voice settings to config/jarvis_settings.json."""
        try:
            cfg = {}
            if SETTINGS_PATH.exists():
                cfg = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            # Remove any old extra keys if present
            for old_key in ("edge_voice", "voice_rate", "voice_pitch", "ultron_dsp"):
                cfg.pop(old_key, None)
            cfg["active_voice_engine"] = self.active_engine
            cfg["voice_name"] = self.active_gemini_voice
            cfg["ultron_voice_id"] = self.ultron_voice_id
            SETTINGS_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[VoiceEngine] Save settings warning: {e}")

    def _ensure_pygame_mixer(self):
        """Initializes pygame mixer if not already active."""
        if not self._pygame_initialized:
            try:
                import pygame
                if not pygame.mixer.get_init():
                    pygame.mixer.init()
                self._pygame_initialized = True
            except Exception as e:
                print(f"[VoiceEngine] Pygame mixer init warning: {e}")

    async def synthesize_ultron_audio(self, text: str) -> bytes:
        """Synthesizes speech using Ultron Voice ID (5HUn8o1WOpG7RxvghslS)."""
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
                        "stability": 0.55,
                        "similarity_boost": 0.85
                    }
                }
                async with httpx.AsyncClient(timeout=12.0) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    if resp.status_code == 200 and len(resp.content) > 500:
                        if len(text) < 120:
                            self._in_memory_cache[cache_key] = resp.content
                        return resp.content
            except Exception as e:
                print(f"[VoiceEngine] ElevenLabs synthesis notice: {e}")

        # Free fallback if no ElevenLabs API key is configured
        import edge_tts
        comm = edge_tts.Communicate(text=text, voice="en-US-ChristopherNeural")
        audio_data = b""
        async for chunk in comm.stream():
            if chunk.get("type") == "audio":
                audio_data += chunk.get("data", b"")

        if len(text) < 120 and audio_data:
            self._in_memory_cache[cache_key] = audio_data

        return audio_data

    def stop(self):
        """Stops currently playing audio."""
        try:
            if self._current_channel and self._current_channel.get_busy():
                self._current_channel.stop()
        except Exception:
            pass

    def speak_ultron(self, text: str, player=None, wait: bool = False):
        """Synthesizes and plays text using the Ultron voice (5HUn8o1WOpG7RxvghslS)."""
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

    def switch_voice(self, target: str, player=None) -> str:
        """
        Switches between the existing voice (Charon) and the new Ultron voice (5HUn8o1WOpG7RxvghslS).
        """
        target_clean = (target or "").lower().strip()

        if any(k in target_clean for k in ["ultron", ULTRON_VOICE_ID.lower(), "new"]):
            self.active_engine = "ultron"
            self.ultron_voice_id = ULTRON_VOICE_ID
            self.save_settings()
            msg = f"Voice switched to Ultron ({ULTRON_VOICE_ID})."
            if player and hasattr(player, "write_log"):
                player.write_log(f"SYS: {msg}")
            if player and hasattr(player, "push_notification"):
                player.push_notification(f"Voice: Ultron ({ULTRON_VOICE_ID})", "info")
            self.speak_ultron("Ultron voice online.", player=player)
            return msg

        if any(k in target_clean for k in ["charon", "default", "gemini", "old", "original", "jarvis"]):
            self.active_engine = "gemini_live"
            self.active_gemini_voice = "Charon"
            self.save_settings()
            msg = "Voice switched to Charon (Default)."
            if player and hasattr(player, "write_log"):
                player.write_log(f"SYS: {msg}")
            if player and hasattr(player, "push_notification"):
                player.push_notification("Voice: Charon (Default)", "info")
            if self._reconnect_callback:
                self._reconnect_callback()
            return msg

        return f"Unknown voice '{target}'. Available voices: Charon (default) and Ultron ({ULTRON_VOICE_ID})."

    def list_voices(self) -> Dict[str, Any]:
        """Returns the two configured voices: Charon and Ultron (5HUn8o1WOpG7RxvghslS)."""
        return {
            "active_engine": self.active_engine,
            "voice_name": self.active_gemini_voice,
            "ultron_voice_id": self.ultron_voice_id,
            "voices": AVAILABLE_VOICES
        }


_voice_engine_instance = None

def get_voice_engine() -> VoiceEngine:
    global _voice_engine_instance
    if _voice_engine_instance is None:
        _voice_engine_instance = VoiceEngine()
    return _voice_engine_instance
