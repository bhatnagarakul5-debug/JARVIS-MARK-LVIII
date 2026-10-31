"""
actions/voice_switcher.py — Voice Switcher Action for JARVIS Mark XL
Allows instant voice and engine switching between Gemini Live (Charon, Puck, Fenrir)
and Neural Edge-TTS (Ryan MCU, Christopher, Thomas, Andrew, Brian).
"""

from core.voice_engine import get_voice_engine

def voice_switcher_control(parameters: dict, player=None) -> str:
    """
    Action handler for switching or listing voices.

    parameters:
        action : 'switch' | 'list' | 'current'
        voice  : voice name or engine ('ryan', 'christopher', 'thomas', 'andrew', 'brian', 'charon', 'puck', 'gemini', 'neural')
    """
    params = parameters or {}
    action = params.get("action", "switch").lower().strip()
    target_voice = params.get("voice", "") or params.get("voice_name", "") or params.get("target", "")

    ve = get_voice_engine()

    if action in ("list", "show", "get_voices"):
        voices = ve.list_voices()
        edge_names = [f"{v['name']} ({k})" for k, v in voices["edge_neural_voices"].items()]
        gemini_names = [f"{v['name']} ({k})" for k, v in voices["gemini_live_voices"].items()]
        report = (
            f"Active Engine: {voices['active_engine']}\n"
            f"Current Edge Voice: {voices['active_edge_voice']}\n"
            f"Current Gemini Voice: {voices['active_gemini_voice']}\n\n"
            f"Available Neural Voices: {', '.join(edge_names)}\n"
            f"Available Gemini Live Voices: {', '.join(gemini_names)}"
        )
        if player and hasattr(player, "write_log"):
            player.write_log(f"VOICE: {report}")
        return report

    if action in ("current", "status"):
        return f"Current voice engine is '{ve.active_engine}'. Edge Voice: '{ve.active_edge_voice}', Gemini Voice: '{ve.active_gemini_voice}'."

    # Default action: switch
    if not target_voice:
        target_voice = "ryan"

    result = ve.switch_voice(target_voice, player=player)
    return result
