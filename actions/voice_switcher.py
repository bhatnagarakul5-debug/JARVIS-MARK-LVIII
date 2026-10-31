"""
actions/voice_switcher.py — Voice Switcher Action for JARVIS Mark XL
Switches between:
  - Charon (Default Gemini Live Voice)
  - Ultron (Voice ID: 5HUn8o1WOpG7RxvghslS)
"""

from core.voice_engine import get_voice_engine, ULTRON_VOICE_ID

def voice_switcher_control(parameters: dict, player=None) -> str:
    """
    Action handler for switching between Charon and Ultron (5HUn8o1WOpG7RxvghslS).

    parameters:
        action : 'switch' | 'list' | 'current'
        voice  : 'ultron' | '5HUn8o1WOpG7RxvghslS' | 'charon'
    """
    params = parameters or {}
    action = params.get("action", "switch").lower().strip()
    target_voice = params.get("voice", "") or params.get("voice_name", "") or params.get("target", "")

    ve = get_voice_engine()

    if action in ("list", "show", "get_voices"):
        info = ve.list_voices()
        report = (
            f"Active Engine: {info['active_engine']}\n"
            f"Available Voices:\n"
            f"  1. Charon (Default)\n"
            f"  2. Ultron (Voice ID: {ULTRON_VOICE_ID})"
        )
        if player and hasattr(player, "write_log"):
            player.write_log(f"VOICE: {report}")
        return report

    if action in ("current", "status"):
        active_v = f"Ultron ({ve.ultron_voice_id})" if ve.active_engine == "ultron" else ve.active_gemini_voice
        return f"Current active voice: {active_v}."

    if not target_voice:
        target_voice = "ultron"

    return ve.switch_voice(target_voice, player=player)
