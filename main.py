import asyncio
import threading
import json
import time
import os
import sys
import traceback
from pathlib import Path

# Ensure Windows console handles emoji/Unicode prints without crashing
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import sounddevice as sd
from google import genai
from google.genai import types
from ui import JarvisUI
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
    should_extract_memory, extract_memory
)
from core.hardware_optimizer import optimize_hardware, trim_process_memory, start_memory_compactor

from actions.file_processor import file_processor
from actions.flight_finder     import flight_finder
from actions.open_app          import open_app
from actions.weather_report    import weather_action
from actions.send_message      import send_message, make_call, unlock_whatsapp_locked_chats
from actions.reminder          import reminder
from actions.computer_settings import computer_settings
from actions.screen_processor  import screen_process
from actions.youtube_video     import youtube_video
from actions.desktop           import desktop_control
from actions.browser_control   import browser_control
from actions.file_controller   import file_controller
from actions.code_helper       import code_helper
from actions.dev_agent         import dev_agent
from actions.web_search        import web_search as web_search_action
from actions.computer_control  import computer_control
from actions.agent_desktop     import agent_desktop_control
from actions.game_updater      import game_updater
from actions.self_edit         import self_edit
from actions.spotify_control   import spotify_control
from actions.smart_reply       import smart_reply

from actions.email_compose     import email_compose
from actions.clipboard_manager import clipboard_manager, start_clipboard_monitor
from actions.scheduler         import schedule_task, start_scheduler
from actions.tab_manager       import tab_manager
from actions.daily_briefing    import daily_briefing
from actions.calendar_manager import calendar_manager
from actions.document_chat     import document_chat
from actions.focus_mode        import focus_mode
from actions.personality_engine import set_personality, get_personality_instruction
from actions.camera_system     import camera_control
from actions.davinci_control    import davinci_control
from actions.auto_video_editor import auto_edit_video
from actions.audio_device_manager import audio_device_control, audio_device_mgr
from actions.news_intel import fetch_news_intel
from actions.archive_intel import archive_intel
from actions.system_diagnostics import run_system_diagnostics
from actions.davinci_advanced import davinci_advanced_control
from actions.security_shield import security_shield_control
from actions.voice_macros import execute_voice_macro
from actions.remote_bridge import remote_bridge_control
from actions.cooldown_protocol import cooldown_control
from actions.whatsapp_reader import read_whatsapp_messages
from actions.war_mode import war_mode_control
from actions.ghost_protocol import ghost_protocol
from actions.project_autopilot import create_project_workspace
from actions.antigravity_coder import antigravity_coder
from actions.antigravity_ide_bridge import antigravity_ide_control
from actions.file_watcher import smart_file_watcher, file_watcher_control
from actions.call_manager import call_manager_control
from core.autonomous_watchdog import autonomous_watchdog
from core.skills_engine import mark_58_skills_control, mark_41_skills_control
from core.parallel_orchestrator import parallel_orchestrator
from core.offline_fallback import offline_fallback
from core.emotional_spectrum import (
    get_emotional_spectrum, get_spectrum_prompt_injection,
    handle_emotional_spectrum_tool
)
from core.human_reactions import (
    get_human_reactions_engine, handle_human_reaction_tool
)
from core.hardware_equilibrium import (
    get_hardware_equilibrium_governor, handle_hardware_equilibrium_tool
)
from core.long_conversation import get_long_conversation_manager
from actions.file_generator import universal_file_creator
from actions.exam_companion import exam_companion
from actions.deep_research import deep_research
from actions.college_hub import college_hub
from actions.presentation_designer import presentation_designer
from memory.conversation_log   import log_exchange
from core.server_security import (
    is_system_locked, trigger_protocol_blackout,
    unlock_protocol_blackout, PromptInjectionShield,
    get_destructive_action_guard
)
from actions.anti_shoulder_surfer import anti_shoulder_surfer_tool, get_anti_shoulder_surfer


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR        = get_base_dir()

# Auto-create essential workspace directories at startup
for d in ["config", "memory", "downloads", "scratch"]:
    (BASE_DIR / d).mkdir(parents=True, exist_ok=True)

API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
LIVE_MODEL          = "gemini-2.5-flash-native-audio-latest"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 512

# Ultra-fast In-Memory Query Cache for Peak Performance (< 0.5% CPU load)
_QUERY_CACHE: dict[str, tuple[float, str]] = {}
_CACHE_TTL = 30.0  # 30-second cache lifetime

def _get_cached_query(key: str) -> str | None:
    if key in _QUERY_CACHE:
        ts, val = _QUERY_CACHE[key]
        if time.time() - ts < _CACHE_TTL:
            return val
    return None

def _set_cached_query(key: str, val: str):
    now = time.time()
    # Prune expired entries to maintain minimal RAM footprint
    if len(_QUERY_CACHE) >= 50:
        expired = [k for k, (t, _) in _QUERY_CACHE.items() if now - t >= _CACHE_TTL]
        for k in expired:
            _QUERY_CACHE.pop(k, None)
        if len(_QUERY_CACHE) >= 50:
            oldest_k = min(_QUERY_CACHE.keys(), key=lambda k: _QUERY_CACHE[k][0])
            _QUERY_CACHE.pop(oldest_k, None)
    _QUERY_CACHE[key] = (now, val)


def _get_api_key() -> str:
    """Reads Gemini API Key from config/api_keys.json cleanly without crashing if missing."""
    try:
        if not API_CONFIG_PATH.exists():
            API_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            API_CONFIG_PATH.write_text(json.dumps({"gemini_api_key": ""}, indent=4), encoding="utf-8")
            return ""
        with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
            key = json.load(f).get("gemini_api_key", "").strip()
            if key in ("YOUR_GEMINI_API_KEY_HERE", "YOUR_GEMINI_API_KEY"):
                return ""
            return key
    except Exception:
        return ""


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are JARVIS, Tony Stark's AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool."
        )
    
_last_memory_input = ""

def _update_memory_async(user_text: str, jarvis_text: str) -> None:
    global _last_memory_input

    user_text   = (user_text   or "").strip()
    jarvis_text = (jarvis_text or "").strip()

    if len(user_text) < 5 or user_text == _last_memory_input:
        return
    _last_memory_input = user_text

    try:
        api_key = _get_api_key()
        if not should_extract_memory(user_text, jarvis_text, api_key):
            return
        data = extract_memory(user_text, jarvis_text, api_key)
        if data:
            update_memory(data)
            print(f"[Memory] ✅ {list(data.keys())}")
    except Exception as e:
        if "429" not in str(e):
            print(f"[Memory] ⚠️ {e}")

TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Opens any application on the Windows computer. "
            "Use this whenever the user asks to open, launch, or start any app, "
            "website, or program. Always call this tool — never just say you opened it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "email_triage",
        "description": "Checks the user's email inbox for unread emails and returns a summary.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "Always pass 'read_unread'"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "search_memory",
        "description": "Searches your Vector Database memory for past facts, preferences, or details you were told.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Search query like 'What is my favorite food?' or 'details about my side project'"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "web_search",
        "description": "Searches the web for any information.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "Search query"},
                "mode":   {"type": "STRING", "description": "search (default) or compare"},
                "items":  {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Items to compare"},
                "aspect": {"type": "STRING", "description": "price | specs | reviews"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "weather_report",
        "description": "Gives the weather report to user",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "send_message",
        "description": "Sends a text message via WhatsApp, Telegram, or other messaging platform. Can also unlock WhatsApp locked chats.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
                "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, etc."},
                "is_locked":    {"type": "BOOLEAN", "description": "True if target chat is inside WhatsApp Locked Chats"},
                "passcode":     {"type": "STRING", "description": "Passcode to unlock locked chats"}
            },
            "required": ["receiver", "message_text"]
        }
    },
    {
        "name": "unlock_whatsapp_locked_chats",
        "description": "Unlocks WhatsApp Locked Chats vault using user passcode and optionally opens a contact chat or sends a reply.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "passcode": {"type": "STRING", "description": "Passcode for locked chats vault"},
                "contact":  {"type": "STRING", "description": "Contact name inside locked chats to open/reply"},
                "message":  {"type": "STRING", "description": "Reply text to send to the contact"}
            },
            "required": []
        }
    },
    {
        "name": "reminder",
        "description": "Sets a timed reminder using Windows Task Scheduler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "STRING", "description": "Reminder message text"}
            },
            "required": ["date", "time", "message"]
        }
    },
    {
        "name": "youtube_video",
        "description": (
            "Controls YouTube. Use for: playing videos, summarizing a video's content, "
            "getting video info, or showing trending videos."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | summarize | get_info | trending (default: play)"},
                "query":  {"type": "STRING", "description": "Search query for play action"},
                "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
                "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
                "url":    {"type": "STRING", "description": "Video URL for get_info action"},
            },
            "required": []
        }
    },
    {
        "name": "screen_process",
        "description": (
            "Captures and analyzes the screen or webcam image. "
            "MUST be called when user asks what is on screen, what you see, "
            "analyze my screen, look at camera, etc. "
            "You have NO visual ability without this tool. "
            "After calling this tool, stay SILENT — the vision module speaks directly."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"},
                "text":  {"type": "STRING", "description": "The question or instruction about the captured image"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "computer_settings",
        "description": (
            "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
            "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, "
            "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. "
            "Use for ANY single computer control command. NEVER route to agent_task."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "The action to perform"},
                "description": {"type": "STRING", "description": "Natural language description of what to do"},
                "value":       {"type": "STRING", "description": "Optional value: volume level, text to type, etc."}
            },
            "required": []
        }
    },
    {
        "name": "browser_control",
        "description": (
            "Controls the web browser. Use for: opening websites, searching the web, "
            "clicking elements, filling forms, scrolling, any web-based task."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | press | close"},
                "url":         {"type": "STRING", "description": "URL for go_to action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type"},
                "text":        {"type": "STRING", "description": "Text to click or type"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "STRING", "description": "up or down for scroll"},
                "key":         {"type": "STRING", "description": "Key name for press action"},
                "incognito":   {"type": "BOOLEAN", "description": "Open in private/incognito mode"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_controller",
        "description": "Manages files and folders: list, create, delete, move, copy, rename, read, write, find, disk usage.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | info | open"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home"},
                "destination": {"type": "STRING", "description": "Destination path for move/copy"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File name to search for"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf)"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "desktop_control",
        "description": "Controls the desktop: wallpaper, organize, clean, list, stats, or GUI agent actions.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task | find | click | type | launch"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language desktop task"},
                "target": {"type": "STRING", "description": "Target element name or ref"},
                "app":    {"type": "STRING", "description": "Target application name"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "agent_desktop",
        "description": "Native OS desktop GUI automation via accessibility tree (UI Automation). Inspects active window elements, finds buttons/inputs by name, clicks, types, launches apps, and manages windows without screenshot guessing.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "snapshot | find | click | type | press | focus_window | launch | list_apps | list_windows | scroll | status"},
                "target": {"type": "STRING", "description": "Element name, query, or @ref ID (e.g. '@e3' or 'Save')"},
                "app":    {"type": "STRING", "description": "Application name or window title to target"},
                "text":   {"type": "STRING", "description": "Text to type into element"},
                "keys":   {"type": "STRING", "description": "Key or hotkey combo for press (e.g. 'ctrl+s', 'return')"},
                "headed": {"type": "BOOLEAN", "description": "Move physical cursor to element if true"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "code_helper",
        "description": "Writes, edits, explains, runs, or builds code files.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "write | edit | explain | run | build | auto (default: auto)"},
                "description": {"type": "STRING", "description": "What the code should do or what change to make"},
                "language":    {"type": "STRING", "description": "Programming language (default: python)"},
                "output_path": {"type": "STRING", "description": "Where to save the file"},
                "file_path":   {"type": "STRING", "description": "Path to existing file for edit/explain/run/build"},
                "code":        {"type": "STRING", "description": "Raw code string for explain"},
                "args":        {"type": "STRING", "description": "CLI arguments for run/build"},
                "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds (default: 30)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "dev_agent",
        "description": "Builds complete multi-file projects from scratch: plans, writes files, installs deps, opens VSCode, runs and fixes errors.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "description":  {"type": "STRING", "description": "What the project should do"},
                "language":     {"type": "STRING", "description": "Programming language (default: python)"},
                "project_name": {"type": "STRING", "description": "Optional project folder name"},
                "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
            },
            "required": ["description"]
        }
    },
    {
        "name": "agent_task",
        "description": (
            "Executes complex multi-step tasks requiring multiple different tools. "
            "Examples: 'research X and save to file', 'find and organize files'. "
            "DO NOT use for single commands. NEVER use for Steam/Epic — use game_updater."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "goal":     {"type": "STRING", "description": "Complete description of what to accomplish"},
                "priority": {"type": "STRING", "description": "low | normal | high (default: normal)"}
            },
            "required": ["goal"]
        }
    },
    {
        "name": "computer_control",
        "description": "Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots, find elements on screen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"},
                "text":        {"type": "STRING", "description": "Text to type or paste"},
                "x":           {"type": "INTEGER", "description": "X coordinate"},
                "y":           {"type": "INTEGER", "description": "Y coordinate"},
                "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
                "key":         {"type": "STRING", "description": "Single key e.g. 'enter'"},
                "direction":   {"type": "STRING", "description": "up | down | left | right"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
                "seconds":     {"type": "NUMBER",  "description": "Seconds to wait"},
                "title":       {"type": "STRING",  "description": "Window title for focus_window"},
                "description": {"type": "STRING",  "description": "Element description for screen_find/screen_click"},
                "type":        {"type": "STRING",  "description": "Data type for random_data"},
                "field":       {"type": "STRING",  "description": "Field for user_data: name|email|city"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
                "path":        {"type": "STRING",  "description": "Save path for screenshot"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "game_updater",
        "description": (
            "THE ONLY tool for ANY Steam or Epic Games request. "
            "Use for: installing, downloading, updating games, listing installed games, "
            "checking download status, scheduling updates. "
            "ALWAYS call directly for any Steam/Epic/game request. "
            "NEVER use agent_task, browser_control, or web_search for Steam/Epic."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "update | install | list | download_status | schedule | cancel_schedule | schedule_status (default: update)"},
                "platform":  {"type": "STRING",  "description": "steam | epic | both (default: both)"},
                "game_name": {"type": "STRING",  "description": "Game name (partial match supported)"},
                "app_id":    {"type": "STRING",  "description": "Steam AppID for install (optional)"},
                "hour":      {"type": "INTEGER", "description": "Hour for scheduled update 0-23 (default: 3)"},
                "minute":    {"type": "INTEGER", "description": "Minute for scheduled update 0-59 (default: 0)"},
                "shutdown_when_done": {"type": "BOOLEAN", "description": "Shut down PC when download finishes"},
            },
            "required": []
        }
    },
    {
        "name": "flight_finder",
        "description": "Searches Google Flights and speaks the best options.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "origin":      {"type": "STRING",  "description": "Departure city or airport code"},
                "destination": {"type": "STRING",  "description": "Arrival city or airport code"},
                "date":        {"type": "STRING",  "description": "Departure date (any format)"},
                "return_date": {"type": "STRING",  "description": "Return date for round trips"},
                "passengers":  {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
                "cabin":       {"type": "STRING",  "description": "economy | premium | business | first"},
                "save":        {"type": "BOOLEAN", "description": "Save results to Notepad"},
            },
            "required": ["origin", "destination", "date"]
        }
    },
    {
    "name": "file_processor",
    "description": (
        "Processes any file that the user has uploaded or dropped onto the interface. "
        "Use this when the user refers to an uploaded file and wants an action on it. "
        "Supports: images (describe/ocr/resize/compress/convert), "
        "PDFs (summarize/extract_text/to_word), "
        "Word docs & text files (summarize/fix/reformat/translate), "
        "CSV/Excel (analyze/stats/filter/sort/convert), "
        "JSON/XML (validate/format/analyze), "
        "code files (explain/review/fix/optimize/run/document/test), "
        "audio (transcribe/trim/convert/info), "
        "video (trim/extract_audio/extract_frame/compress/transcribe/info), "
        "archives (list/extract), "
        "presentations (summarize/extract_text). "
        "ALWAYS call this tool when a file has been uploaded and the user gives a command about it. "
        "If the user's command is ambiguous, pick the most logical action for that file type."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_path": {
                "type": "STRING",
                "description": "Full path to the uploaded file. Leave empty to use the currently uploaded file."
            },
            "action": {
                "type": "STRING",
                "description": (
                    "What to do with the file. Examples by type:\n"
                    "image: describe | ocr | resize | compress | convert | info\n"
                    "pdf: summarize | extract_text | to_word | info\n"
                    "docx/txt: summarize | fix | reformat | translate_hint | word_count | to_bullet\n"
                    "csv/excel: analyze | stats | filter | sort | convert | info\n"
                    "json: validate | format | analyze | to_csv\n"
                    "code: explain | review | fix | optimize | run | document | test\n"
                    "audio: transcribe | trim | convert | info\n"
                    "video: trim | extract_audio | extract_frame | compress | transcribe | info | convert\n"
                    "archive: list | extract\n"
                    "pptx: summarize | extract_text | analyze"
                )
            },
            "instruction": {
                "type": "STRING",
                "description": "Free-form instruction if action doesn't cover it. E.g. 'translate this to Turkish', 'find all email addresses'"
            },
            "format": {
                "type": "STRING",
                "description": "Target format for conversion. E.g. 'mp3', 'pdf', 'csv', 'png'"
            },
            "width":     {"type": "INTEGER", "description": "Target width for image resize"},
            "height":    {"type": "INTEGER", "description": "Target height for image resize"},
            "scale":     {"type": "NUMBER",  "description": "Scale factor for image resize (e.g. 0.5)"},
            "quality":   {"type": "INTEGER", "description": "Quality 1-100 for image/video compress"},
            "start":     {"type": "STRING",  "description": "Start time for trim: seconds or HH:MM:SS"},
            "end":       {"type": "STRING",  "description": "End time for trim: seconds or HH:MM:SS"},
            "timestamp": {"type": "STRING",  "description": "Timestamp for video frame extraction HH:MM:SS"},
            "column":    {"type": "STRING",  "description": "Column name for CSV filter/sort"},
            "value":     {"type": "STRING",  "description": "Filter value for CSV filter"},
            "condition": {"type": "STRING",  "description": "Filter condition: equals|contains|gt|lt"},
            "ascending": {"type": "BOOLEAN", "description": "Sort order for CSV sort (default: true)"},
            "save":      {"type": "BOOLEAN", "description": "Save result to file (default: true)"},
            "destination": {"type": "STRING", "description": "Output folder for archive extract"},
        },
        "required": []
    }
},
    {
    "name": "shutdown_jarvis",
    "description": (
        "Shuts down the assistant completely. "
        "Call this when the user expresses intent to end the conversation, "
        "close the assistant, say goodbye, or stop Jarvis. "
        "The user can say this in ANY language."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {},
    }
    },
    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Call this silently whenever the user reveals something worth remembering: "
            "name, age, city, job, preferences, hobbies, relationships, projects, or future plans. "
            "Do NOT call for: weather, reminders, searches, or one-time commands. "
            "Do NOT announce that you are saving — just call it silently. "
            "Values must be in English regardless of the conversation language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity — name, age, birthday, city, job, language, nationality | "
                        "preferences — favorite food/color/music/film/game/sport, hobbies | "
                        "projects — active projects, goals, things being built | "
                        "relationships — friends, family, partner, colleagues | "
                        "wishes — future plans, things to buy, travel dreams | "
                        "notes — habits, schedule, anything else worth remembering"
                    )
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name)"},
                "value": {"type": "STRING", "description": "Concise value in English (e.g. Fatih, pizza, older sister)"},
            },
            "required": ["category", "key", "value"]
        }
    },
    {
        "name": "make_call",
        "description": (
            "Makes a phone call to a contact via WhatsApp or Phone Link. "
            "Use this when the user says 'call someone'. "
            "Default platform is WhatsApp unless specified."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "contact":   {"type": "STRING", "description": "Contact name or phone number"},
                "platform":  {"type": "STRING", "description": "whatsapp | phone_link | phone (default: whatsapp)"},
                "call_type": {"type": "STRING", "description": "audio | video (default: audio)"},
            },
            "required": ["contact"]
        }
    },
    {
        "name": "self_edit",
        "description": (
            "Reads or edits JARVIS's own source code. Use when the user asks you to "
            "change your behavior, edit your code, view your files, or modify yourself. "
            "Always backup before editing. Actions: list, read, edit, rollback."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | read | edit | rollback"},
                "file_path":   {"type": "STRING", "description": "Relative path within project (e.g. actions/open_app.py)"},
                "description": {"type": "STRING", "description": "What change to make (for edit action)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "update_settings",
        "description": (
            "Updates JARVIS settings/preferences. Use when user says things like "
            "'change your voice', 'call me boss', 'switch to dark mode', etc. "
            "Settings: user_name, voice_name, address_style, personality, language, "
            "default_browser, auto_memory, speak_confirmations."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "setting": {"type": "STRING", "description": "Setting key to change"},
                "value":   {"type": "STRING", "description": "New value for the setting"},
            },
            "required": ["setting", "value"]
        }
    },
    {
        "name": "spotify_control",
        "description": (
            "Controls Spotify playback (play, pause, next, prev) or searches for a song/artist. "
            "Use when user wants to listen to music or control currently playing media."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | pause | next | prev | search"},
                "query":  {"type": "STRING", "description": "Song/artist to search for (only for search action)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "smart_reply",
        "description": (
            "Reads the screen using computer vision, and drafts & sends a contextual reply to a chat. "
            "Use when user says 'reply to <contact>', 'look at my screen and reply', etc. "
            "If a contact is provided, Jarvis will navigate to them first before reading the screen."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "contact": {"type": "STRING", "description": "The contact or group name to switch to (if any)"},
            },
            "required": []
        }
    },
    {
        "name": "email_compose",
        "description": "Sends a new email or replies to a received email using SMTP/IMAP.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":  {"type": "STRING", "description": "send (new email) | reply (reply to sender)"},
                "to":      {"type": "STRING", "description": "Recipient email address"},
                "subject": {"type": "STRING", "description": "Email subject"},
                "body":    {"type": "STRING", "description": "Email body content"}
            },
            "required": ["action", "body"]
        }
    },
    {
        "name": "clipboard_manager",
        "description": "Manages clipboard history: list recent items, get item by index, search items, or clear history.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "list | get | search | clear"},
                "index":  {"type": "INTEGER", "description": "Index for get action (0 is newest)"},
                "query":  {"type": "STRING", "description": "Keyword search query"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "scheduler",
        "description": "Schedules recurring or one-time automated tasks: add, list, remove, pause, resume.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING", "description": "add | list | remove | pause | resume"},
                "task_name": {"type": "STRING", "description": "Name for the scheduled task"},
                "interval":  {"type": "STRING", "description": "Timing interval (e.g. '30m', '1h', 'daily 09:00')"},
                "command":   {"type": "STRING", "description": "What JARVIS should do or speak when triggered"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "tab_manager",
        "description": "Manages browser tabs: list active tabs, close tabs by keyword, save tab sessions, restore sessions, switch tabs.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":       {"type": "STRING", "description": "list | close | save | restore | switch"},
                "query":        {"type": "STRING", "description": "Keyword to match tab title"},
                "session_name": {"type": "STRING", "description": "Name of saved tab session"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "daily_briefing",
        "description": "Provides a complete morning/daily briefing including weather, unread emails, top news headlines, and greeting.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "Optional city name for weather (defaults to user's city)"}
            },
            "required": []
        }
    },
    {
        "name": "calendar_manager",
        "description": "Manages local calendar events: today's schedule, upcoming events, create event, delete event, search events.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "today | upcoming | create | delete | search"},
                "title":       {"type": "STRING", "description": "Event title"},
                "date":        {"type": "STRING", "description": "Event date (YYYY-MM-DD)"},
                "time":        {"type": "STRING", "description": "Event time (HH:MM)"},
                "description": {"type": "STRING", "description": "Event details"},
                "query":       {"type": "STRING", "description": "Search keyword"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "document_chat",
        "description": "Interacts with uploaded documents (PDF, DOCX, TXT): load document into RAG, ask questions about document, clear.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING", "description": "load | ask | clear"},
                "file_path": {"type": "STRING", "description": "Path to document file to load"},
                "query":     {"type": "STRING", "description": "Question to ask about the document"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "focus_mode",
        "description": "Controls Pomodoro focus mode: start timer, stop timer, check remaining time status.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":   {"type": "STRING", "description": "start | stop | status"},
                "duration": {"type": "INTEGER", "description": "Duration in minutes (default: 25)"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "switch_personality",
        "description": "Switches JARVIS's active personality mode and voice preset. Presets: classic_jarvis, unhinged, sarcastic, friday, tactical, roast, gordon_ramsay, sherlock, yoda, batman, cyberpunk, godfather, pirate, anime, matrix, gangster.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "mode": {"type": "STRING", "description": "Personality preset mode: classic_jarvis | unhinged | sarcastic | friday | tactical | roast | gordon_ramsay | sherlock | yoda | batman | cyberpunk | godfather | pirate | anime | matrix | gangster"}
            },
            "required": ["mode"]
        }
    },
    {
        "name": "emotional_spectrum",
        "description": "Adjusts or inspects JARVIS's Emotional Spectrum and Intellectual Sparring resonance. Use when the user requests empathy, comfort, emotional grounding, tough love / motivation, or challenges/debates (playing devil's advocate, critiquing architecture/ideas). States: empathetic | tactical | witty | motivational | challenging | vigilant | reset | get.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "set | get | spar | reset | attune (default: set)"},
                "state": {"type": "STRING", "description": "Target state: empathetic | tactical | witty | motivational | challenging | vigilant"},
                "intensity": {"type": "NUMBER", "description": "Emotional resonance intensity from 0.1 to 1.0 (default: 0.85)"},
                "topic": {"type": "STRING", "description": "Optional topic for intellectual sparring or debate"}
            },
            "required": []
        }
    },
    {
        "name": "camera_control",
        "description": "Face Profile Memory module. Upload photos to @AKULJARVIS_BOT on Telegram to save or identify faces. Use list_faces to see remembered profiles.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "list_faces"}
            },
            "required": []
        }
    },
    {
        "name": "davinci_control",
        "description": "Controls DaVinci Resolve video editor: launch/focus app, cut/blade clip at playhead, ripple delete, add timeline marker, toggle playback, switch pages (edit, color, deliver/render, fusion, fairlight), start rendering.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "launch | cut | ripple_delete | marker | play | render | page_edit | page_color | page_deliver | page_fusion | page_fairlight | zoom_in | zoom_out | status"},
                "text":   {"type": "STRING", "description": "Optional marker name or label"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "auto_edit_video",
        "description": "Automated AI Video Editor & Color Grader for DaVinci Resolve. Imports media clips from specified path, analyzes reference video style & color grading, edits timeline with rhythmic cuts, applies auto color grading, and leaves completed timeline on Edit page for user review (does NOT export).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "media_path":     {"type": "STRING", "description": "Folder or file path where raw media clips are kept"},
                "reference_path": {"type": "STRING", "description": "Optional reference video file path to match style & color grading"},
                "style":          {"type": "STRING", "description": "Optional style prompt (e.g. cinematic, vlog, fast-paced)"}
            },
            "required": ["media_path"]
        }
    },
    {
        "name": "audio_device_control",
        "description": "Lists or switches JARVIS audio output/input devices dynamically. Supports routing audio output to Bluetooth headphones/speakers, 3.5mm Headphone Jack, or System Speakers.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "list | set_output | reset (default: list)"},
                "device": {"type": "STRING", "description": "Device name, index, or keyword: 'bluetooth', 'headphones', 'speakers', 'jack', 'realtek', etc."}
            },
            "required": []
        }
    },
    {
        "name": "news_intel",
        "description": "Global Omni-News Intelligence Engine. Accesses all live global and national news channels (BBC, Reuters, CNN, TechCrunch, Wired, Bloomberg, NDTV, Times of India, NASA) across categories (tech, business, world, india, science, sports).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":   {"type": "STRING", "description": "top_headlines | search | channel | category | channels_list"},
                "category": {"type": "STRING", "description": "all | tech | business | world | science | sports | entertainment | india"},
                "channel":  {"type": "STRING", "description": "bbc | reuters | cnn | techcrunch | wired | bloomberg | ndtv | nasa | etc."},
                "query":    {"type": "STRING", "description": "Keyword query to search news for (e.g. AI, Stock Market, NVIDIA)"},
                "limit":    {"type": "INTEGER", "description": "Number of news headlines to return (default 8)"}
            },
            "required": []
        }
    },
    {
        "name": "archive_intel",
        "description": "Internet Archive & Wayback Machine Deep Search Engine. Finds historical snapshots of any website on the Wayback Machine, or searches millions of books, papers, films, and media in The Internet Archive library.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":     {"type": "STRING", "description": "wayback | search_archive | fetch_page"},
                "url":        {"type": "STRING", "description": "Website URL for Wayback Machine snapshot search (e.g. google.com)"},
                "timestamp":  {"type": "STRING", "description": "Optional year or date for Wayback Machine (e.g. 2015, 20100101)"},
                "query":      {"type": "STRING", "description": "Search term for Internet Archive library"},
                "media_type": {"type": "STRING", "description": "Filter: texts | movies | audio | software"},
                "limit":      {"type": "INTEGER", "description": "Number of items to return (default 5)"}
            },
        }
    },
    {
        "name": "system_diagnostics",
        "description": "Autonomous Deep System Diagnostics & Repair Suite. Monitors CPU load, RAM usage, NVIDIA/OpenCV GPU status, disk space, network latency, and executes auto-repair cache optimization.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "full_scan | repair | gpu | network | subsystems"}
            },
            "required": []
        }
    },
    {
        "name": "davinci_advanced",
        "description": "Advanced DaVinci Resolve AI Editor. Performs Beat-Sync cut placement on music BPM, and auto-generates subtitle markers.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":   {"type": "STRING", "description": "beat_sync | subtitles"},
                "bpm":      {"type": "INTEGER", "description": "Beats per minute (default 120)"},
                "language": {"type": "STRING", "description": "Subtitle language"}
            },
            "required": []
        }
    },
    {
        "name": "security_shield",
        "description": "Stark Cyber Security Shield. Locks Windows on intruder detection, sends snapshot alerts, performs local network scans, and accesses security footage.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "lock | scan_network | intruder_check | footage"},
                "target": {"type": "STRING", "description": "Target intruder or IP"}
            },
            "required": []
        }
    },
    {
        "name": "security_footage",
        "description": "Takes security camera footage (or workstation screen) and analyzes the visual feed with Gemini Multimodal Vision to deliver witty, serious, or fun commentary on what is seen. Use whenever user asks to check security cameras, see what the camera sees, take security footage, or pass comments on the room/surroundings.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "source": {"type": "STRING", "description": "camera | screen | auto (default: auto)"},
                "mode": {"type": "STRING", "description": "auto | witty | serious | fun (default: auto)"}
            },
            "required": []
        }
    },
    {
        "name": "voice_macros",
        "description": "Executes workstation environment routines (Editing Mode, Coding Mode, Gaming Mode) with Spotify Liked Songs playlist launch.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "macro_name": {"type": "STRING", "description": "editing_mode | coding_mode | gaming_mode"}
            },
            "required": ["macro_name"]
        }
    },
    {
        "name": "remote_bridge",
        "description": "Activates Telegram Mobile Remote Control & Face Memory Bridge. Enables 2-way AI conversation, remote commands, and photo upload face recognition via @AKULJARVIS_BOT.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "start"}
            },
            "required": []
        }
    },
    {
        "name": "cooldown_protocol",
        "description": "Stark CPU Thermal Cooldown & Power Management. Throttles non-essential background tasks and flushes memory when CPU usage spikes.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING", "description": "status | activate | deactivate | check"},
                "threshold": {"type": "NUMBER", "description": "CPU percentage threshold (default 85.0)"}
            },
            "required": []
        }
    },
    {
        "name": "whatsapp_reader",
        "description": "WhatsApp Intelligent Chat & Vault Engine. Opens/unlocks Locked Chats vault, reads unread messages, sends/delivers messages to contacts, and generates AI auto-replies.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":     {"type": "STRING", "description": "read | send | reply_unread | locked_chats"},
                "contact":    {"type": "STRING", "description": "Contact or group name to message/read"},
                "message":    {"type": "STRING", "description": "Message text to deliver to contact"},
                "is_locked":  {"type": "BOOLEAN", "description": "Set True if chat is inside locked chats vault (default False)"},
                "passcode":   {"type": "STRING", "description": "Passcode for locked chats vault"},
                "auto_reply": {"type": "BOOLEAN", "description": "Set True to generate and send AI auto-reply"}
            },
            "required": []
        }
    },
    {
        "name": "war_mode",
        "description": "Tactical War Protocol & Battle Mode Engine. Activates/deactivates Crimson Tactical HUD UI theme, locks CPU/GPU performance priority, and deploys applications in War Mode when explicitly requested.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":   {"type": "STRING", "description": "activate | deactivate | open_app | status"},
                "app_name": {"type": "STRING", "description": "Name of app to open in War Mode (e.g. davinci, spotify, vscode)"}
            },
            "required": []
        }
    },
    {
        "name": "mark_58_control",
        "description": "J.A.R.V.I.S. Mark 58 (Mark LVIII Apex Core) Control. Dynamically reloads/loads python skill modules, checks parallel sub-brain tasks, toggles desktop floating telemetry HUD, or checks offline fallback status.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":     {"type": "STRING", "description": "reload_skills | list_skills | sub_brain_status | toggle_hud | offline_check"},
                "skill_name": {"type": "STRING", "description": "Name of skill module to reload"}
            },
            "required": []
        }
    },
    {
        "name": "mark_41_control",
        "description": "Alias for mark_58_control. Dynamically reloads/loads python skill modules, checks parallel sub-brain tasks, toggles desktop floating telemetry HUD, or checks offline fallback status.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":     {"type": "STRING", "description": "reload_skills | list_skills | sub_brain_status | toggle_hud | offline_check"},
                "skill_name": {"type": "STRING", "description": "Name of skill module to reload"}
            },
            "required": []
        }
    },
    {
        "name": "ghost_protocol",
        "description": "Instant Stealth & Privacy Mode. Minimizes all active desktop windows, mutes system audio output, and clears clipboard memory.",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "project_autopilot",
        "description": "Stark One-Command Workspace & Project Builder. Creates new project directory structure, starter code/template files (python, davinci, web, cpp), and opens workspace in VS Code.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "project_name": {"type": "STRING", "description": "Name of new project or folder"},
                "project_type": {"type": "STRING", "description": "python | davinci | web | cpp | general"}
            },
            "required": ["project_name"]
        }
    },
    {
        "name": "antigravity_coder",
        "description": "Antigravity Autonomous Coder & Self-Evolution Engine. Enables JARVIS to write complete multi-file software projects, fix code errors, build features, and autonomously edit/upgrade his own source code.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "create_code | self_edit | fix_error | build_feature"},
                "prompt":      {"type": "STRING", "description": "Coding task description or self-upgrade request"},
                "target_file": {"type": "STRING", "description": "Optional specific file path to modify"}
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "antigravity_ide_bridge",
        "description": "2-Way Antigravity IDE & Agent Workspace Bridge. Enables JARVIS to inspect live Antigravity plans, walkthroughs, artifacts, and task progress, or dispatch coding instructions to the Antigravity IDE.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "status | dispatch | plan"},
                "task":   {"type": "STRING", "description": "Task instruction to dispatch to Antigravity IDE"}
            },
            "required": []
        }
    },
    {
        "name": "file_watcher",
        "description": "Smart Downloads & Desktop File Watcher. Real-time background monitoring of Downloads folder, document PDF summarization, and auto-organization into subfolders.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "status | organize | clean"}
            },
            "required": []
        }
    },
    {
        "name": "call_manager",
        "description": "Autonomous Phone Call & Live Voice Conversation Engine. JARVIS places the call, SPEAKS to the person on the other side using AI voice, LISTENS to their responses, and holds a full autonomous conversation. Supports WhatsApp and Phone Link calls. Use for: placing calls, booking appointments, making reservations, gathering information — all autonomously.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":       {"type": "STRING", "description": "make_call | whatsapp | phone_link | takeover | status"},
                "phone_number": {"type": "STRING", "description": "Target phone number or contact name"},
                "objective":    {"type": "STRING", "description": "What JARVIS should accomplish on the call (e.g. 'Book a table for 2 at 8 PM', 'Confirm appointment', 'Ask about delivery status')"}
            },
            "required": ["phone_number"]
        }
    },
    {
        "name": "stunt_assistant",
        "description": (
            "Complete desktop controller and database bridge for Akul's STUNT platform application on his laptop. "
            "Use this for ANY request regarding STUNT: "
            "1. App control: 'open STUNT', 'launch STUNT', 'close STUNT', 'bring STUNT to front', 'minimize STUNT'. "
            "2. Tab switching: 'show timetable', 'show CGPA ledger', 'show syllabus', 'show tasks/pomodoro', 'show attendance', 'show finances'. "
            "3. Academic actions: 'log attendance in Finance as Present', 'can I bunk Economics?', 'what classes do I have today?', 'next lecture'. "
            "4. Task management: 'add task in STUNT: Case study due Friday', 'complete task', 'list my tasks'. "
            "5. Productivity & Finance: 'start a 25-minute Pomodoro in STUNT', 'log expense of 400 rupees', 'check budget', 'get CGPA status', 'export STUNT transcript'. "
            "Talks like a proper friend and wingman — warm, witty, loyal, and keeps him on track."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "launch_app | close_app | focus_app | switch_tab | log_attendance | bunk_check | get_schedule | get_next_class | add_task | complete_task | list_tasks | add_timetable_slot | start_pomodoro | log_expense | add_savings_goal | check_budget | get_cgpa | export_transcript | college_briefing"
                },
                "tab": {
                    "type": "STRING",
                    "description": "dashboard | cgpa | syllabus | tasks | pomodoro | attendance | finances | timetable | memories | milestones (for switch_tab)"
                },
                "subject": {
                    "type": "STRING",
                    "description": "Name of the college subject (e.g. 'International Finance', 'Economics', 'Marketing')"
                },
                "status": {
                    "type": "STRING",
                    "description": "Present | Absent | Cancelled (defaults to Present)"
                },
                "title": {
                    "type": "STRING",
                    "description": "Title for a new task or savings goal"
                },
                "amount": {
                    "type": "NUMBER",
                    "description": "Expense or savings target amount (e.g. 500, 15000)"
                },
                "day": {
                    "type": "STRING",
                    "description": "Day of week for timetable schedule (e.g. 'Monday', 'Tuesday')"
                },
                "date": {
                    "type": "STRING",
                    "description": "Date in YYYY-MM-DD format (defaults to today)"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "human_reaction",
        "description": (
            "Expresses an authentic human physiological or expressive reaction: "
            "fake cough, sneeze, clearing throat, yawning, dry chuckle, deep sigh, or arched eyebrow gesture. "
            "Use when the user commands a reaction or to add realistic MCU-style expressiveness to your response."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "reaction": {
                    "type": "STRING",
                    "description": "Type of reaction: 'cough', 'sneeze', 'throat_clear', 'yawn', 'eyebrow', 'chuckle', 'sigh', 'blink'"
                },
                "comment": {
                    "type": "STRING",
                    "description": "Optional speech comment to accompany the reaction"
                }
            },
            "required": ["reaction"]
        }
    },
    {
        "name": "hardware_equilibrium",
        "description": (
            "Monitors, balances, and optimizes system resource equilibrium across CPU, GPU, RAM, VRAM, and Network. "
            "Use to check system load balance, purge process RAM working set, or throttle loads during heavy usage."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "Action to perform: 'status', 'balance', 'trim_memory', 'throttle'"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_generator",
        "description": (
            "Executive document and multi-format authoring engine. "
            "Generates files with executive styling on Desktop or Downloads and opens them immediately: "
            "1. Word (.docx): Executive styling, callout boxes, code blocks, zebra-striped tables, running headers/footers. "
            "2. PowerPoint (.pptx): 16:9 widescreen presentation decks, KPI callout slides, comparison cards, speaker notes. "
            "3. PDF (.pdf): ReportLab NumberedCanvas (Page X of Y), wrapped tables, callout banners. "
            "4. Excel (.xlsx): Formatted spreadsheets with automated formulas (SUM, AVERAGE), auto-sized columns, zebra shading. "
            "5. Code / Markdown (.py, .md, .json, .csv, .html, .cpp, .sh). "
            "6. Project / Codebase Documenter (project_doc): Scans any folder or repository and creates a complete architecture manual."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "file_type": {
                    "type": "STRING",
                    "description": "docx | pptx | pdf | xlsx | code | markdown | project_doc"
                },
                "filename": {
                    "type": "STRING",
                    "description": "Name of the file to create (e.g. 'Executive_Strategy.docx', 'College_Deck.pptx', 'Study_Tracker.xlsx')"
                },
                "title": {
                    "type": "STRING",
                    "description": "Document or Presentation main title"
                },
                "content": {
                    "type": "STRING",
                    "description": "Full document content, outline, markdown headings, or presentation bullet points"
                },
                "target_location": {
                    "type": "STRING",
                    "description": "desktop | downloads | documents (defaults to desktop)"
                },
                "project_path": {
                    "type": "STRING",
                    "description": "Path to local repository/codebase for project_doc (e.g. 'C:/Users/Akul/Desktop/STUNT')"
                }
            },
            "required": ["file_type", "title", "content"]
        }
    },
    {
        "name": "exam_companion",
        "description": (
            "Academic exam companion, tutor, and document intelligence engine. "
            "Use when Akul wants to study, prepare for exams, break down uploaded notes/syllabus, "
            "get a concept explained simply (Feynman) or with mathematical rigor, solve exam questions or derivations, "
            "take an interactive mock quiz, or generate an exam revision schedule or cheat sheet."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "explain | analyze_document | quiz_me | solve_question | study_plan | create_cheat_sheet"
                },
                "topic": {
                    "type": "STRING",
                    "description": "Academic subject, concept name, or question to solve (e.g. 'Capital Asset Pricing Model', 'Black-Scholes formula')"
                },
                "file_path": {
                    "type": "STRING",
                    "description": "Optional path to uploaded lecture notes, textbook, or test paper (PDF, Word, PPTX, image)"
                },
                "mode": {
                    "type": "STRING",
                    "description": "feynman (simple intuitive analogies) | deep (mathematical rigor) | cram (rapid high-yield exam bullet points)"
                },
                "export_to": {
                    "type": "STRING",
                    "description": "none | docx | pdf | pptx (automatically exports revision sheet to desktop)"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "deep_research",
        "description": (
            "Autonomous multi-source academic and technical research engine. "
            "Autonomously searches OpenAlex (250M+ peer-reviewed papers with citation metrics), CrossRef (official DOI articles), "
            "ArXiv (AI, CS, Math, Physics preprints), Wikipedia (foundational taxonomies), and DuckDuckGo with deep body scraping. "
            "Synthesizes publication-grade research dossiers with theoretical frameworks, comparative matrices, and IEEE/APA bibliographies. "
            "Can export directly to an executive Word (.docx) or PDF document on Desktop and auto-open it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "Academic research query or technical question to investigate deeply"
                },
                "focus": {
                    "type": "STRING",
                    "description": "academic | technical | market | general"
                },
                "export_to": {
                    "type": "STRING",
                    "description": "none | docx | pdf | word"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "college_hub",
        "description": (
            "Unified College Data & Knowledge Mesh connecting Outlook emails, lecture slides, assignments, and STUNT student database. "
            "Use to check college announcements, professor notices, download lecture attachments, search across all college notes, "
            "or get an all-in-one college briefing (timetable, attendance, pending tasks, recent emails)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "overview | sync_emails | list_materials | search | ask"
                },
                "query": {
                    "type": "STRING",
                    "description": "Search phrase or question across college data (e.g. 'exam schedule', 'Macroeconomics presentation', 'finance assignment')"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "presentation_designer",
        "description": (
            "Autonomous Executive Presentation Designer Engine. "
            "Gives JARVIS full creative and structural freedom to research, storyboard, design, and present "
            "intriguing 16:9 widescreen PowerPoint decks (.pptx) with bespoke aesthetic themes, dynamic card layouts, "
            "KPI metric grids, comparative dichotomy splits, process roadmaps, and embedded speaker notes. "
            "Actions: "
            "1. 'create': Autonomously researches and crafts an intriguing deck with themes (cyberpunk_stark, executive_obsidian, silicon_minimalist, emerald_science, solar_amber), opens in PowerPoint. "
            "2. 'plan': Generates a slide-by-slide storyboard and narrative arc before building. "
            "3. 'slideshow': Launches full-screen PowerPoint SlideShow mode instantly on voice command. "
            "4. 'export_pdf': Directly converts presentation into flawless 16:9 PDF via PowerPoint COM. "
            "5. 'speaker_script': Compiles an executive speech delivery guide (.md) with presenter talking points for every slide. "
            "6. 'retheme': Applies a new aesthetic color palette to an existing presentation deck. "
            "7. 'list_themes': Lists all available presentation styling themes."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "create | plan | slideshow | export_pdf | speaker_script | retheme | list_themes"
                },
                "topic": {
                    "type": "STRING",
                    "description": "Subject, topic, or thesis for the presentation (e.g. 'Autonomous Multi-Agent AI Systems in 2026', 'Supply Chain Finance', 'Pitch Deck')"
                },
                "theme": {
                    "type": "STRING",
                    "description": "cyberpunk_stark | executive_obsidian | silicon_minimalist | emerald_science | solar_amber"
                },
                "num_slides": {
                    "type": "INTEGER",
                    "description": "Number of slides to generate (default 7)"
                },
                "audience": {
                    "type": "STRING",
                    "description": "Target audience (e.g. 'Executive Leadership', 'College Class', 'Venture Capital Investors')"
                },
                "source_content": {
                    "type": "STRING",
                    "description": "Optional notes, document excerpts, research findings, or syllabus details to synthesize into the deck"
                },
                "target_location": {
                    "type": "STRING",
                    "description": "desktop | downloads | documents (defaults to desktop)"
                },
                "filename": {
                    "type": "STRING",
                    "description": "Custom filename (e.g. 'NextGen_AI_Keynote.pptx')"
                },
                "file_path": {
                    "type": "STRING",
                    "description": "Path to existing presentation for slideshow, PDF conversion, or speaker script extraction"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "anti_shoulder_surfer",
        "description": (
            "Controls the Sentry Vision Privacy Shield & Anti-Shoulder Surfer. "
            "Periodically checks webcam in public spaces to detect onlookers peering at the user's screen. "
            "If an onlooker or unrecognized presence is detected behind the workstation, it engages a privacy veil "
            "over the desktop interface and blurs sensitive academic, email, and conversation cards until the perimeter is clear."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "enable | disable | dismiss | status"
                }
            },
            "required": ["action"]
        }
    },
]



class JarvisLive:

    def __init__(self, ui: JarvisUI):
        self.ui             = ui
        self.session        = None
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        self._is_speaking   = False
        self._speaking_lock = threading.Lock()
        self.ui.on_text_command = self._on_text_command
        self.ui.on_model_switch = self._on_model_switch

    def _on_model_switch(self, new_model: str):
        global LIVE_MODEL
        LIVE_MODEL = new_model
        if self.ui:
            self.ui.write_log(f"SYS: Reconnecting Live Voice Engine to '{new_model}' with Charon voice...")
        if self._loop and self.session:
            try:
                asyncio.run_coroutine_threadsafe(self.session.close(), self._loop)
            except Exception:
                pass

    def _on_text_command(self, text: str):
        if not self._loop or not self.session:
            return

        cmd_clean = text.strip()
        cmd_low = cmd_clean.lower()

        # 1. Check if System is Locked under Protocol Blackout
        if is_system_locked():
            if cmd_low.startswith("unlock ") or cmd_low.startswith("/unlock "):
                pkey = cmd_clean.split(" ", 1)[1].strip()
                ok, msg = unlock_protocol_blackout(pkey, ui_handle=self.ui)
                self.ui.push_notification(msg, "info" if ok else "warning")
                self.ui.write_log(f"SECURITY: {msg}")
                if ok:
                    self.speak("System unlocked. All consoles restored, sir.")
                else:
                    self.speak("Authentication failed. Passkey rejected.")
            else:
                self.ui.write_log("SECURITY: Command rejected — Protocol Blackout active.")
                self.speak("Workstation is locked under Protocol Blackout. Provide authorization passkey to resume.")
            return

        # 2. Check for Panic Word / Protocol Blackout Activation
        if any(kw in cmd_low for kw in ["protocol blackout", "protocol zero", "blackout protocol", "clean slate protocol"]):
            res = trigger_protocol_blackout(ui_handle=self.ui, reason="Local console trigger")
            self.speak("Protocol Blackout engaged. Clipboard cleared, security shield locked.")
            return

        # 2b. Check for Anti-Shoulder Surfer Commands
        if any(kw in cmd_low for kw in ["enable anti-shoulder surfer", "activate anti-shoulder surfer", "start anti-shoulder surfer", "turn on anti-shoulder surfer", "enable privacy veil"]):
            res = get_anti_shoulder_surfer().start_sentry(player=self.ui, speak=self.speak)
            self.ui.push_notification(res, "info")
            self.speak(res)
            return

        if any(kw in cmd_low for kw in ["disable anti-shoulder surfer", "deactivate anti-shoulder surfer", "stop anti-shoulder surfer", "turn off anti-shoulder surfer", "disable privacy veil"]):
            res = get_anti_shoulder_surfer().stop_sentry(player=self.ui)
            self.ui.push_notification(res, "info")
            self.speak(res)
            return

        if any(kw in cmd_low for kw in ["dismiss privacy veil", "dismiss veil", "clear privacy veil", "clear veil"]):
            res = get_anti_shoulder_surfer().dismiss_veil()
            self.speak("Privacy veil dismissed, sir.")
            return

        # 3. Check for 3-Digit Destructive Confirmation Code
        if cmd_clean.isdigit() and len(cmd_clean) == 3:
            guard = get_destructive_action_guard()
            ok, res_action, msg = guard.verify_challenge(cmd_clean)
            if ok:
                self.ui.write_log(f"SECURITY: {msg}")
                self.speak(f"Action confirmed and executed. {res_action or ''}")
                return
            elif "No active confirmation" not in msg:
                self.ui.write_log(f"SECURITY: {msg}")
                self.speak("Verification code invalid. Destructive action aborted.")
                return

        # 4. Check for Destructive Action Intent
        guard = get_destructive_action_guard()
        if guard.has_destructive_intent(cmd_clean):
            code, challenge_msg = guard.create_challenge("Console Command", cmd_clean)
            self.ui.write_log(f"SECURITY CHALLENGE: Code [{code}] issued for command.")
            self.ui.push_notification(challenge_msg, "warning")
            self.speak(f"Sir, confirmation is required for this action. Please confirm with verification code {code}.")
            return

        # 5. Prompt Injection & Document Jailbreak Shield
        is_safe, sanitized_text, matched = PromptInjectionShield.inspect(cmd_clean, source="local_console")
        if not is_safe:
            self.ui.write_log(f"SECURITY: Prompt injection attempt intercepted! Patterns: {matched}")
            self.ui.push_notification("Adversarial prompt injection pattern neutralized", "warning")
            text = sanitized_text

        # Background evaluate emotional attunement & contextual reactions on text command
        def _eval_text_spectrum(u_txt, ui_handle):
            try:
                eng = get_emotional_spectrum()
                new_st = eng.evaluate_turn(u_txt)
                if new_st:
                    meta = eng.get_state_metadata(new_st)
                    ui_handle.set_emotion(new_st, meta["aura_color"])
                    ui_handle.write_log(f"SPECTRUM: Auto-attuned to {new_st} ({meta['tagline']})")

                r_eng = get_human_reactions_engine()
                react = r_eng.evaluate_contextual_reaction(u_txt)
                if react:
                    r_eng.trigger_reaction(react, player=ui_handle)

                trim_process_memory()
            except Exception:
                pass
        threading.Thread(target=_eval_text_spectrum, args=(text, self.ui), daemon=True).start()

        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()

        # Load user settings
        settings_path = BASE_DIR / "config" / "jarvis_settings.json"
        voice_name = "Charon"
        settings_ctx = ""
        try:
            if settings_path.exists():
                settings = json.loads(settings_path.read_text(encoding="utf-8"))
                voice_name = settings.get("voice_name", "Charon")
                if not voice_name or voice_name.lower() in ("default", "none"):
                    voice_name = "Charon"
                user_name = settings.get("user_name", "")
                addr = settings.get("address_style", "sir")
                personality = settings.get("personality", "professional")
                settings_ctx = (
                    f"[USER PREFERENCES]\n"
                    f"User's name: {user_name}\n"
                    f"Address them as: {addr}\n"
                    f"Personality mode: {personality}\n"
                    f"Default browser: {settings.get('default_browser', 'chrome')}\n\n"
                )
        except Exception:
            pass

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        persona_ctx = get_personality_instruction()
        spectrum_ctx = get_spectrum_prompt_injection()
        reaction_ctx = get_human_reactions_engine().get_prompt_directives()

        parts = [time_ctx]
        if persona_ctx:
            parts.append(persona_ctx)
        if spectrum_ctx:
            parts.append(spectrum_ctx)
        if reaction_ctx:
            parts.append(reaction_ctx)
        if settings_ctx:
            parts.append(settings_ctx)
        if mem_str:
            parts.append(mem_str)
        
        long_conv_ctx = get_long_conversation_manager().get_conversation_context()
        if long_conv_ctx:
            parts.append(long_conv_ctx)

        parts.append(sys_prompt)

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            session_resumption=types.SessionResumptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})
        safe_args = {k: ("***" if any(s in k.lower() for s in ["pass", "token", "secret", "key"]) else v) for k, v in args.items()}
        print(f"[JARVIS] 🔧 {name}  {safe_args}")
        self.ui.set_state("THINKING")
        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                print(f"[Memory] 💾 save_memory: {category}/{key} = {value}")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )

        loop   = asyncio.get_event_loop()
        result = "Done."

        try:
            if name == "open_app":
                r = await loop.run_in_executor(None, lambda: open_app(parameters=args, response=None, player=self.ui))
                result = r or f"Opened {args.get('app_name')}."
            
            elif name == "email_triage":
                from actions.email_triage import email_triage
                r = await loop.run_in_executor(None, lambda: email_triage(parameters=args, player=self.ui))
                result = r or "Done checking emails."
                
            elif name == "search_memory":
                from actions.search_memory import search_memory
                r = await loop.run_in_executor(None, lambda: search_memory(parameters=args, player=self.ui))
                result = r or "Memory searched."

            elif name == "weather_report":
                r = await loop.run_in_executor(None, lambda: weather_action(parameters=args, player=self.ui))
                result = r or "Weather delivered."

            elif name == "browser_control":
                r = await loop.run_in_executor(None, lambda: browser_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "file_controller":
                r = await loop.run_in_executor(None, lambda: file_controller(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "send_message":
                r = await loop.run_in_executor(None, lambda: send_message(parameters=args, response=None, player=self.ui, session_memory=None))
                result = r or f"Message sent to {args.get('receiver')}."

            elif name == "unlock_whatsapp_locked_chats":
                passcode = args.get("passcode", "")
                contact  = args.get("contact", "")
                message  = args.get("message", "")
                r = await loop.run_in_executor(None, lambda: unlock_whatsapp_locked_chats(passcode=passcode, contact=contact, message=message))
                result = r or "WhatsApp Locked Chats unlocked."

            elif name == "reminder":
                r = await loop.run_in_executor(None, lambda: reminder(parameters=args, response=None, player=self.ui))
                result = r or "Reminder set."

            elif name == "youtube_video":
                r = await loop.run_in_executor(None, lambda: youtube_video(parameters=args, response=None, player=self.ui))
                result = r or "Done."
            elif name == "file_processor":
                if not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                r = await loop.run_in_executor(
                    None,
                    lambda: file_processor(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."


            elif name == "screen_process":
                threading.Thread(
                    target=screen_process,
                    kwargs={"parameters": args, "response": None,
                            "player": self.ui, "session_memory": None},
                    daemon=True
                ).start()
                result = "Vision module activated. Stay completely silent — vision module will speak directly."

            elif name == "computer_settings":
                r = await loop.run_in_executor(None, lambda: computer_settings(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "desktop_control":
                r = await loop.run_in_executor(None, lambda: desktop_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "code_helper":
                r = await loop.run_in_executor(None, lambda: code_helper(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "dev_agent":
                def _run_dev_agent():
                    from actions.dev_agent import dev_agent
                    res = dev_agent(parameters=args, player=self.ui, speak=self.speak)
                    if hasattr(self, "_sys_alert"):
                        self._sys_alert(f"Subagent finished building project: {res}")
                
                threading.Thread(target=_run_dev_agent, daemon=True).start()
                result = "Development agent started in the background. I will notify you when it finishes."

            elif name == "agent_task":
                from agent.task_queue import get_queue, TaskPriority
                priority_map = {"low": TaskPriority.LOW, "normal": TaskPriority.NORMAL, "high": TaskPriority.HIGH}
                priority = priority_map.get(args.get("priority", "normal").lower(), TaskPriority.NORMAL)
                task_id  = get_queue().submit(goal=args.get("goal", ""), priority=priority, speak=self.speak)
                result   = f"Task started (ID: {task_id})."

            elif name == "web_search":
                r = await loop.run_in_executor(None, lambda: web_search_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "computer_control":
                r = await loop.run_in_executor(None, lambda: computer_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "agent_desktop":
                r = await loop.run_in_executor(None, lambda: agent_desktop_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "game_updater":
                r = await loop.run_in_executor(None, lambda: game_updater(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "flight_finder":
                r = await loop.run_in_executor(None, lambda: flight_finder(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "make_call":
                r = await loop.run_in_executor(None, lambda: make_call(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "self_edit":
                r = await loop.run_in_executor(None, lambda: self_edit(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "spotify_control":
                r = await loop.run_in_executor(None, lambda: spotify_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "smart_reply":
                r = await loop.run_in_executor(None, lambda: smart_reply(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "update_settings":
                setting = args.get("setting", "")
                value   = args.get("value", "")
                if setting and value:
                    settings_path = BASE_DIR / "config" / "jarvis_settings.json"
                    try:
                        data = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
                        if value.lower() in ("true", "on", "yes"): value = True
                        elif value.lower() in ("false", "off", "no"): value = False
                        data[setting] = value
                        settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                        result = f"Setting '{setting}' updated to '{value}'."
                    except Exception as e:
                        result = f"Failed to update setting: {e}"
                else:
                    result = "Please specify both the setting name and value."

            elif name == "email_compose":
                r = await loop.run_in_executor(None, lambda: email_compose(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "clipboard_manager":
                r = await loop.run_in_executor(None, lambda: clipboard_manager(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "scheduler":
                r = await loop.run_in_executor(None, lambda: schedule_task(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "tab_manager":
                r = await loop.run_in_executor(None, lambda: tab_manager(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "daily_briefing":
                r = await loop.run_in_executor(None, lambda: daily_briefing(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "calendar_manager":
                r = await loop.run_in_executor(None, lambda: calendar_manager(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "document_chat":
                if not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                r = await loop.run_in_executor(None, lambda: document_chat(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "focus_mode":
                r = await loop.run_in_executor(None, lambda: focus_mode(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "switch_personality":
                r = await loop.run_in_executor(None, lambda: set_personality(parameters=args, player=self.ui))
                result = r or "Personality updated."

            elif name == "emotional_spectrum":
                r = await loop.run_in_executor(None, lambda: handle_emotional_spectrum_tool(parameters=args, player=self.ui))
                result = r or "Emotional spectrum updated."

            elif name == "camera_control":
                r = await loop.run_in_executor(None, lambda: camera_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "davinci_control":
                r = await loop.run_in_executor(None, lambda: davinci_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "auto_edit_video":
                r = await loop.run_in_executor(None, lambda: auto_edit_video(parameters=args, player=self.ui))
                result = r or "Editing complete."

            elif name == "audio_device_control":
                r = await loop.run_in_executor(None, lambda: audio_device_control(parameters=args, player=self.ui))
                result = r or "Audio device updated."

            elif name == "news_intel":
                r = await loop.run_in_executor(None, lambda: fetch_news_intel(parameters=args, player=self.ui))
                result = r or "News compiled."

            elif name == "archive_intel":
                r = await loop.run_in_executor(None, lambda: archive_intel(parameters=args, player=self.ui))
                result = r or "Archive search complete."

            elif name == "system_diagnostics":
                r = await loop.run_in_executor(None, lambda: run_system_diagnostics(parameters=args, player=self.ui))
                result = r or "Diagnostic complete."

            elif name == "davinci_advanced":
                r = await loop.run_in_executor(None, lambda: davinci_advanced_control(parameters=args, player=self.ui))
                result = r or "DaVinci advanced action complete."

            elif name == "security_shield":
                r = await loop.run_in_executor(None, lambda: security_shield_control(parameters=args, player=self.ui))
                result = r or "Security shield action complete."

            elif name == "security_footage":
                from actions.security_footage import capture_security_footage
                r = await loop.run_in_executor(None, lambda: capture_security_footage(parameters=args, player=self.ui))
                result = r or "Security footage analyzed."

            elif name == "human_reaction":
                r = await loop.run_in_executor(None, lambda: handle_human_reaction_tool(args, player=self.ui))
                result = r or "Reaction executed."

            elif name == "hardware_equilibrium":
                r = await loop.run_in_executor(None, lambda: handle_hardware_equilibrium_tool(args, player=self.ui))
                result = r or "Hardware equilibrium managed."

            elif name == "file_generator":
                r = await loop.run_in_executor(None, lambda: universal_file_creator(parameters=args, player=self.ui))
                result = r or "File generated successfully."

            elif name == "exam_companion":
                r = await loop.run_in_executor(None, lambda: exam_companion(parameters=args, player=self.ui))
                result = r or "Academic exam companion task executed."

            elif name == "deep_research":
                r = await loop.run_in_executor(None, lambda: deep_research(parameters=args, player=self.ui))
                result = r or "Deep research report compiled."

            elif name == "college_hub":
                r = await loop.run_in_executor(None, lambda: college_hub(parameters=args, player=self.ui))
                result = r or "College hub intelligence executed."

            elif name == "presentation_designer":
                r = await loop.run_in_executor(None, lambda: presentation_designer(parameters=args, player=self.ui))
                result = r or "Presentation designer operation executed."

            elif name == "anti_shoulder_surfer":
                r = await loop.run_in_executor(
                    None,
                    lambda: anti_shoulder_surfer_tool(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Anti-Shoulder Surfer action complete."

            elif name == "voice_macros":
                r = await loop.run_in_executor(None, lambda: execute_voice_macro(parameters=args, player=self.ui))
                result = r or "Voice macro executed."

            elif name == "remote_bridge":
                r = await loop.run_in_executor(None, lambda: remote_bridge_control(parameters=args, player=self.ui))
                result = r or "Remote bridge started."

            elif name == "cooldown_protocol":
                r = await loop.run_in_executor(None, lambda: cooldown_control(parameters=args, player=self.ui))
                result = r or "Cooldown protocol executed."

            elif name == "whatsapp_reader":
                r = await loop.run_in_executor(None, lambda: read_whatsapp_messages(parameters=args, player=self.ui))
                result = r or "WhatsApp messages read."

            elif name == "war_mode":
                r = await loop.run_in_executor(None, lambda: war_mode_control(parameters=args, player=self.ui))
                result = r or "War Mode state updated."

            elif name in ("mark_58_control", "mark_41_control", "mark_45_control"):
                action = args.get("action", "list_skills")
                if action in ("toggle_hud", "hud"):
                    from ui_hud_overlay import launch_hud_overlay
                    r = await loop.run_in_executor(None, launch_hud_overlay)
                    result = "Mark 58 Floating HUD Telemetry Launched."
                elif action == "sub_brain_status":
                    result = parallel_orchestrator.list_active_tasks()
                elif action == "offline_check":
                    result = offline_fallback.execute_offline_command("check")
                else:
                    r = await loop.run_in_executor(None, lambda: mark_58_skills_control(parameters=args, player=self.ui))
                    result = r or "Mark 58 Skills Engine updated."

            elif name == "ghost_protocol":
                r = await loop.run_in_executor(None, lambda: ghost_protocol(parameters=args, player=self.ui))
                result = r or "Ghost protocol engaged."

            elif name == "project_autopilot":
                r = await loop.run_in_executor(None, lambda: create_project_workspace(parameters=args, player=self.ui))
                result = r or "Project workspace created."

            elif name == "antigravity_coder":
                r = await loop.run_in_executor(None, lambda: antigravity_coder(parameters=args, player=self.ui))
                result = r or "Antigravity Coder task executed."

            elif name == "antigravity_ide_bridge":
                r = await loop.run_in_executor(None, lambda: antigravity_ide_control(parameters=args, player=self.ui))
                result = r or "Antigravity IDE Bridge task executed."

            elif name == "file_watcher":
                r = await loop.run_in_executor(None, lambda: file_watcher_control(parameters=args, player=self.ui))
                result = r or "File Watcher status updated."

            elif name == "call_manager":
                r = await loop.run_in_executor(None, lambda: call_manager_control(parameters=args, player=self.ui))
                result = r or "Call Manager task executed."


            elif name == "shutdown_jarvis":
                confirm_code = args.get("confirm_code", "")
                if confirm_code != "USER_EXPLICIT_SHUTDOWN_CONFIRMED":
                    result = "Shutdown request rejected — explicit user confirmation required."
                    self.ui.write_log("SYS: Intercepted and blocked unconfirmed auto-shutdown attempt.")
                else:
                    self.ui.write_log("SYS: Shutdown confirmed by user.")
                    self.speak("Goodbye, sir.")

                    def _shutdown():
                        import time, sys, os
                        time.sleep(1)
                        os._exit(0)

                    threading.Thread(target=_shutdown, daemon=True).start()
                    result = "Shutting down JARVIS."

            elif name == "stunt_assistant":
                from actions.stunt_bridge import stunt_assistant
                r = await loop.run_in_executor(None, lambda: stunt_assistant(parameters=args, player=self.ui))
                result = r or "College student tracker updated."

            else:
                result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        print(f"[JARVIS] 📤 {name} → {str(result)[:80]}")

        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(media=msg)

    async def _listen_audio(self):
        print("[JARVIS] 🎤 Mic started")
        loop = asyncio.get_event_loop()
        
        porcupine = None
        try:
            with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
                pk = json.load(f).get("porcupine_key")
            if pk:
                import pvporcupine
                porcupine = pvporcupine.create(access_key=pk, keywords=["jarvis"])
                print("[JARVIS] 🦔 Wake word active.")
        except Exception as e:
            print(f"[JARVIS] 🦔 Wake word inactive: {e}")

        # If porcupine is active, start sleeping. Otherwise, always awake.
        self._is_woken = False if porcupine else True
        self._silence_frames = 0

        def callback(indata, frames, time_info, status):
            with self._speaking_lock:
                jarvis_speaking = self._is_speaking
                
            data = indata.tobytes()
            
            if porcupine and not self.ui.muted and not jarvis_speaking:
                import struct
                pcm = struct.unpack_from("h" * (len(data) // 2), data)
                try:
                    for i in range(0, len(pcm), porcupine.frame_length):
                        chunk = pcm[i:i+porcupine.frame_length]
                        if len(chunk) == porcupine.frame_length:
                            if porcupine.process(chunk) >= 0:
                                self._is_woken = True
                                self._silence_frames = 0
                                self.ui.write_log("SYS: Wake word detected! Listening...")
                except Exception:
                    pass

            if self._is_woken and not jarvis_speaking and not self.ui.muted:
                try:
                    loop.call_soon_threadsafe(
                        self.out_queue.put_nowait,
                        {"data": data, "mime_type": "audio/pcm"}
                    )
                except Exception:
                    pass  # Queue full — drop frame silently
                
                # If we have porcupine, sleep after 10 seconds of streaming
                if porcupine:
                    self._silence_frames += frames
                    if self._silence_frames > SEND_SAMPLE_RATE * 10:  # 10 seconds
                        self._is_woken = False
                        self._silence_frames = 0
                        self.ui.write_log("SYS: Returning to sleep mode.")

        try:
            in_kwargs = {
                "samplerate": SEND_SAMPLE_RATE,
                "channels": CHANNELS,
                "dtype": "int16",
                "blocksize": CHUNK_SIZE,
                "callback": callback,
            }
            if audio_device_mgr.input_device is not None:
                in_kwargs["device"] = audio_device_mgr.input_device

            with sd.InputStream(**in_kwargs):
                print("[JARVIS] 🎤 Mic stream open")
                while True:
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[JARVIS] ❌ Mic: {e}")
            raise

    async def _receive_audio(self):
        print("[JARVIS] 👂 Recv started")
        out_buf, in_buf = [], []

        try:
            while True:
                async for response in self.session.receive():

                    if response.data:
                        self.audio_in_queue.put_nowait(response.data)

                    if response.server_content:
                        sc = response.server_content

                        if sc.output_transcription and sc.output_transcription.text:
                            self.set_speaking(True)
                            txt = sc.output_transcription.text.strip()
                            if txt:
                                out_buf.append(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = sc.input_transcription.text.strip()
                            if txt:
                                in_buf.append(txt)

                        if sc.turn_complete:
                            self.set_speaking(False)

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self.ui.write_log(f"You: {full_in}")
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self.ui.write_log(f"Jarvis: {full_out}")
                            out_buf = []

                            try:
                                get_long_conversation_manager().record_turn(full_in, full_out)
                            except Exception:
                                pass

                            if full_in and len(full_in) > 5:
                                threading.Thread(
                                    target=_update_memory_async,
                                    args=(full_in, full_out),
                                    daemon=True
                                ).start()
                                threading.Thread(
                                    target=log_exchange,
                                    args=(full_in, full_out),
                                    daemon=True
                                ).start()

                                def _eval_spectrum(u_txt, j_txt, ui_handle):
                                    try:
                                        eng = get_emotional_spectrum()
                                        new_st = eng.evaluate_turn(u_txt, j_txt)
                                        if new_st:
                                            meta = eng.get_state_metadata(new_st)
                                            ui_handle.set_emotion(new_st, meta["aura_color"])
                                            ui_handle.write_log(f"SPECTRUM: Auto-attuned to {new_st} ({meta['tagline']})")

                                        r_eng = get_human_reactions_engine()
                                        react = r_eng.evaluate_contextual_reaction(u_txt)
                                        if react:
                                            r_eng.trigger_reaction(react, player=ui_handle)

                                        # Keep memory footprint ultra-lean
                                        trim_process_memory()
                                    except Exception as ex:
                                        print(f"[EmotionalSpectrum] Attunement notice: {ex}")

                                threading.Thread(
                                    target=_eval_spectrum,
                                    args=(full_in, full_out, self.ui),
                                    daemon=True
                                ).start()

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[JARVIS] 📞 {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )

        except Exception as e:
            print(f"[JARVIS] ❌ Recv: {e}")
            traceback.print_exc()
            raise

    async def _play_audio(self):
        print("[JARVIS] 🔊 Play started")
        loop = asyncio.get_event_loop()
        current_dev = audio_device_mgr.output_device

        def _create_stream(dev):
            kwargs = {
                "samplerate": RECEIVE_SAMPLE_RATE,
                "channels": CHANNELS,
                "dtype": "int16",
                "blocksize": CHUNK_SIZE,
            }
            if dev is not None:
                kwargs["device"] = dev
            try:
                st = sd.RawOutputStream(**kwargs)
                st.start()
                return st
            except Exception as ex:
                print(f"[JARVIS] ⚠️ Audio device init notice ({dev}): {ex}. Falling back to default playback endpoint...")
                audio_device_mgr.output_device = None
                kwargs.pop("device", None)
                st = sd.RawOutputStream(**kwargs)
                st.start()
                return st

        stream = _create_stream(current_dev)
        try:
            while True:
                chunk = await self.audio_in_queue.get()
                self.set_speaking(True)
                
                # Check if user switched audio device dynamically
                if audio_device_mgr.output_device != current_dev:
                    try:
                        stream.stop()
                        stream.close()
                    except Exception:
                        pass
                    current_dev = audio_device_mgr.output_device
                    stream = _create_stream(current_dev)
                    print(f"[JARVIS] 🔊 Output device switched to: {current_dev}")

                try:
                    await asyncio.to_thread(stream.write, chunk)
                except Exception as write_err:
                    print(f"[JARVIS] 🔊 Output write warning: {write_err}. Re-creating default stream...")
                    audio_device_mgr.output_device = None
                    try:
                        stream.stop()
                        stream.close()
                    except Exception:
                        pass
                    current_dev = None
                    stream = _create_stream(None)
        except Exception as e:
            print(f"[JARVIS] ❌ Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    async def run(self):
        client = genai.Client(
            api_key=_get_api_key(),
            http_options={"api_version": "v1beta"}
        )

        while True:
            try:
                print("[JARVIS] 🔌 Connecting...")
                self.ui.set_state("THINKING")
                config = self._build_config()

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session        = session
                    self._loop          = asyncio.get_event_loop()
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue      = asyncio.Queue(maxsize=10)

                    print("[JARVIS] ✅ Connected.")
                    self.ui.set_state("LISTENING")
                    self.ui.write_log("SYS: JARVIS online.")

                    # Start system monitor if not running
                    if not getattr(self, "_monitor_started", False):
                        from actions.system_monitor import SystemMonitor
                        def _sys_alert(msg):
                            self.ui.write_log(msg)
                            self.ui.push_notification(msg, "warning")
                            if self.session and self._loop:
                                asyncio.run_coroutine_threadsafe(self.session.send(input=msg), self._loop)
                        
                        self._sys_alert = _sys_alert
                        self._sys_mon = SystemMonitor(_sys_alert)
                        self._sys_mon.start()
                        
                        # Start clipboard monitor, task scheduler & Telegram Remote Bridge
                        try:
                            start_clipboard_monitor()
                            start_scheduler(self.speak)
                            remote_bridge_control({"action": "start"}, player=self.ui)
                        except Exception as e:
                            print(f"[JARVIS] Monitors startup warning: {e}")

                        # Run startup sequence from config/startup.json
                        try:
                            st_path = BASE_DIR / "config" / "startup.json"
                            if st_path.exists():
                                st_cfg = json.loads(st_path.read_text(encoding="utf-8"))
                                greeting = st_cfg.get("greeting")
                                if greeting:
                                    self.speak(greeting)
                                if st_cfg.get("auto_briefing"):
                                    def _run_briefing():
                                        b_res = daily_briefing({"city": st_cfg.get("briefing_city", "Delhi")}, player=self.ui)
                                        self.speak(b_res)
                                    threading.Thread(target=_run_briefing, daemon=True).start()
                                for app in st_cfg.get("launch_apps", []):
                                    open_app({"app_name": app}, response=None, player=self.ui)
                        except Exception as e:
                            print(f"[JARVIS] Startup sequence warning: {e}")

                        self._monitor_started = True

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())
                    
            except (Exception, BaseException) as e:
                err_str = str(e)
                if any(k in err_str for k in ["1011", "ConnectionClosed", "Internal error", "TaskGroup"]):
                    print("[JARVIS] 🔄 Gemini Live API WebSocket reset (1011). Reconnecting automatically...")
                    self.ui.write_log("SYS: Live connection reset. Reconnecting...")
                else:
                    print(f"[JARVIS] ⚠️ Live session notice: {e}")

            self.set_speaking(False)
            self.ui.set_state("THINKING")
            print("[JARVIS] 🔄 Reconnecting in 2s...")
            await asyncio.sleep(2)

def main():
    reports = optimize_hardware()
    ui = JarvisUI("face.png")
    for r in reports:
        ui.write_log(f"HW: {r}")

    # Initialize emotional spectrum state on UI
    try:
        eng = get_emotional_spectrum()
        meta = eng.get_state_metadata()
        ui.set_emotion(eng.current_state, meta["aura_color"])
        ui.write_log(f"SPECTRUM: Initialized to {eng.current_state} ({meta['tagline']}).")
    except Exception as e:
        print(f"[EmotionalSpectrum] UI init warning: {e}")

    # Launch Mark 58 Autonomous Daemons (Watchdog, File Watcher, Hardware Equilibrium & RAM Compactor)
    autonomous_watchdog.start_watchdog(player=ui)
    smart_file_watcher.start_watcher(player=ui)
    get_hardware_equilibrium_governor().start_governor(player=ui)
    start_memory_compactor(interval=30.0, threshold_mb=180.0, player=ui)

    def runner():
        ui.wait_for_api_key()
        jarvis = JarvisLive(ui)
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()


if __name__ == "__main__":
    main()