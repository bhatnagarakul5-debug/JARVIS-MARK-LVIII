"""
actions/voice_switcher.py — Voice & Ultron DSP Switcher Action for JARVIS Mark XL
Allows instant voice switching between:
  - Ultron (Voice ID: 5HUn8o1WOpG7RxvghslS + 6-Stage DSP Chain)
  - Gemini Live (Charon, Puck, Fenrir, Aoede, Kore)
  - Neural Edge-TTS (Ryan MCU, Christopher, Thomas, Andrew, Brian, Sonia)
And real-time adjustment of the 6-stage Ultron DSP effects rack.
"""

from core.voice_engine import get_voice_engine

def voice_switcher_control(parameters: dict, player=None) -> str:
    """
    Action handler for switching voices or tuning Ultron DSP parameters.

    parameters:
        action : 'switch' | 'list' | 'current' | 'dsp'
        voice  : voice name or ID ('ultron', '5HUn8o1WOpG7RxvghslS', 'ryan', 'christopher', 'thomas', 'charon', etc.)
        pitch_semitones    : float (default -1.5, range -1 to -2 semitones)
        bass_boost_db      : float (default 3.5 dB — Slight boost)
        metallic_resonance : float (default 0.14 — Subtle)
        reverb_mix         : float (default 0.08 — Very light)
        compression_ratio  : float (default 3.2 — Moderate)
        stereo_doubling    : float (default 0.11 — Very subtle)
    """
    params = parameters or {}
    action = params.get("action", "switch").lower().strip()
    target_voice = params.get("voice", "") or params.get("voice_name", "") or params.get("target", "")

    ve = get_voice_engine()

    if action in ("dsp", "effects", "update_dsp", "set_dsp"):
        return ve.update_dsp_settings(params, player=player)

    if action in ("list", "show", "get_voices"):
        voices = ve.list_voices()
        edge_names = [f"{v['name']} ({k})" for k, v in voices["edge_neural_voices"].items()]
        gemini_names = [f"{v['name']} ({k})" for k, v in voices["gemini_live_voices"].items()]
        dsp = voices["ultron_dsp"]
        report = (
            f"Active Engine: {voices['active_engine']}\n"
            f"Current Neural/Ultron Voice: {voices['active_edge_voice']}\n"
            f"Current Gemini Voice: {voices['active_gemini_voice']}\n"
            f"Ultron Voice ID: {voices['ultron_voice_id']}\n"
            f"Ultron 6-Stage DSP Active: {dsp.get('enabled')} "
            f"(Pitch: {dsp.get('pitch_semitones')} st | Bass: +{dsp.get('bass_boost_db')} dB | "
            f"Metallic: {dsp.get('metallic_resonance')} | Reverb: {dsp.get('reverb_mix')} | "
            f"Compression: {dsp.get('compression_ratio')}:1 | Stereo Doubling: {dsp.get('stereo_doubling')})\n\n"
            f"Available Neural / Hybrid Voices: {', '.join(edge_names)}\n"
            f"Available Gemini Live Voices: {', '.join(gemini_names)}"
        )
        if player and hasattr(player, "write_log"):
            player.write_log(f"VOICE: {report}")
        return report

    if action in ("current", "status"):
        dsp = ve.ultron_dsp
        return (
            f"Current voice engine is '{ve.active_engine}'. "
            f"Active Voice: '{ve.active_edge_voice if ve.active_engine == 'edge_neural' else ve.active_gemini_voice}'. "
            f"Ultron Voice ID: '{ve.ultron_voice_id}'. "
            f"Ultron DSP Enabled: {dsp.get('enabled')}."
        )

    # Default action: switch
    if not target_voice:
        target_voice = "ultron"

    result = ve.switch_voice(target_voice, player=player)
    return result
