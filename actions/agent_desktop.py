"""
actions/agent_desktop.py — Vercel Labs agent-desktop Integration for J.A.R.V.I.S. Mark LVIII
Deterministic computer use via native OS accessibility trees (UI Automation on Windows).
Replaces slow, fragile screenshot/vision coordinate guessing with rock-solid semantic refs.
"""

import os
import sys
import json
import time
import subprocess
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List, Union

def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = _get_base_dir()


class AgentDesktop:
    """
    Python wrapper for Vercel Labs' agent-desktop CLI.
    Interacts with Windows UI Automation via deterministic @ref IDs.
    """

    def __init__(self):
        self._bin_path = self._locate_binary()
        self._last_snapshot: Optional[Dict[str, Any]] = None

    def _locate_binary(self) -> str:
        """Finds agent-desktop or agent-desktop-win32-x64 binary."""
        # 1. Check system PATH
        path_bin = shutil.which("agent-desktop")
        if path_bin:
            return path_bin

        # 2. Check npm global paths on Windows
        appdata = os.environ.get("APPDATA", "")
        npm_bin = Path(appdata) / "npm" / "agent-desktop.cmd"
        if npm_bin.exists():
            return str(npm_bin)

        # 3. Fallback to direct name
        return "agent-desktop"

    def run_cmd(self, args: List[str], timeout: int = 25) -> Dict[str, Any]:
        """
        Executes an agent-desktop CLI command and returns parsed JSON.
        """
        cmd = [self._bin_path] + [str(a) for a in args]
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                shell=(sys.platform == "win32")
            )
            stdout = res.stdout.strip()
            if not stdout and res.stderr:
                return {
                    "ok": False,
                    "error": {
                        "code": "CLI_ERROR",
                        "message": res.stderr.strip()
                    }
                }

            # Attempt JSON parse
            try:
                data = json.loads(stdout)
                return data
            except json.JSONDecodeError:
                # Fallback if raw text
                return {
                    "ok": res.returncode == 0,
                    "raw_output": stdout,
                    "stderr": res.stderr.strip()
                }

        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error": {
                    "code": "TIMEOUT",
                    "message": f"agent-desktop command timed out after {timeout}s"
                }
            }
        except Exception as e:
            return {
                "ok": False,
                "error": {
                    "code": "EXECUTION_EXCEPTION",
                    "message": str(e)
                }
            }

    # ==========================================
    # System & App Management
    # ==========================================

    def status(self) -> Dict[str, Any]:
        """Checks adapter health and permissions."""
        return self.run_cmd(["status"])

    def list_apps(self, filter_name: Optional[str] = None) -> Dict[str, Any]:
        """Lists running GUI applications."""
        args = ["list-apps"]
        if filter_name:
            args.extend(["--app", filter_name])
        return self.run_cmd(args)

    def list_windows(self, app: Optional[str] = None) -> Dict[str, Any]:
        """Lists visible windows."""
        args = ["list-windows"]
        if app:
            args.extend(["--app", app])
        return self.run_cmd(args)

    def focus_window(self, title_or_app: str) -> Dict[str, Any]:
        """Brings an application window to the foreground."""
        return self.run_cmd(["focus-window", title_or_app])

    def launch(self, app_name: str, activate: bool = True) -> Dict[str, Any]:
        """Launches a desktop application."""
        args = ["launch", app_name]
        if activate:
            args.append("--activate")
        return self.run_cmd(args, timeout=30)

    def close_app(self, app_name: str, force: bool = False) -> Dict[str, Any]:
        """Closes an application."""
        args = ["close-app", app_name]
        if force:
            args.append("--force")
        return self.run_cmd(args)

    # ==========================================
    # Observation (Accessibility Tree)
    # ==========================================

    def snapshot(
        self,
        app: Optional[str] = None,
        root_ref: Optional[str] = None,
        compact: bool = True,
        interactive_only: bool = True,
        skeleton: bool = False,
        wait_for: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Captures the accessibility tree as structured JSON with @ref IDs.
        """
        args = ["snapshot"]
        if app:
            args.extend(["--app", app])
        if root_ref:
            # Quote ref for PowerShell/Windows safety
            clean_ref = root_ref.strip("'\"")
            args.extend(["--root", clean_ref])
        if compact:
            args.append("--compact")
        if interactive_only:
            args.append("-i")
        if skeleton:
            args.append("--skeleton")
        if wait_for:
            args.extend(["--wait-for", wait_for])

        res = self.run_cmd(args)
        if res.get("ok"):
            self._last_snapshot = res
        return res

    def find(
        self,
        query: str,
        app: Optional[str] = None,
        role: Optional[str] = None,
        exact: bool = False,
    ) -> Dict[str, Any]:
        """
        Finds actionable UI elements by text content, name, or role.
        """
        args = ["find"]
        if app:
            args.extend(["--app", app])
        if role:
            args.extend(["--role", role])
        if exact:
            args.append("--exact")
            if query:
                args.extend(["--name", query])
        else:
            if query:
                args.extend(["--text", query])
        return self.run_cmd(args)

    # ==========================================
    # Deterministic Ref Actions
    # ==========================================

    def click(self, ref: str, headed: bool = False) -> Dict[str, Any]:
        """Clicks an element by its @ref ID."""
        clean_ref = ref.strip("'\"")
        args = ["click", clean_ref]
        if headed:
            args.append("--headed")
        return self.run_cmd(args)

    def double_click(self, ref: str) -> Dict[str, Any]:
        """Double clicks an element by ref (headed)."""
        clean_ref = ref.strip("'\"")
        return self.run_cmd(["double-click", clean_ref, "--headed"])

    def right_click(self, ref: str, headed: bool = False) -> Dict[str, Any]:
        """Right-clicks an element by ref."""
        clean_ref = ref.strip("'\"")
        args = ["right-click", clean_ref]
        if headed:
            args.append("--headed")
        return self.run_cmd(args)

    def type_text(self, ref: str, text: str) -> Dict[str, Any]:
        """Types text into an element by ref."""
        clean_ref = ref.strip("'\"")
        return self.run_cmd(["type", clean_ref, text])

    def set_value(self, ref: str, value: str) -> Dict[str, Any]:
        """Sets element value directly."""
        clean_ref = ref.strip("'\"")
        return self.run_cmd(["set-value", clean_ref, value])

    def clear(self, ref: str) -> Dict[str, Any]:
        """Clears text inside an element."""
        clean_ref = ref.strip("'\"")
        return self.run_cmd(["clear", clean_ref])

    def press(self, key_combo: str) -> Dict[str, Any]:
        """Sends key combinations (e.g. 'ctrl+c', 'return', 'tab', 'escape')."""
        return self.run_cmd(["press", key_combo])

    def scroll(
        self,
        ref: Optional[str] = None,
        direction: str = "down",
        amount: int = 3
    ) -> Dict[str, Any]:
        """Scrolls element or active window."""
        args = ["scroll", "--direction", direction, "--amount", str(amount)]
        if ref:
            args.append(ref.strip("'\""))
        return self.run_cmd(args)

    def wait(self, element_ref: Optional[str] = None, timeout_ms: int = 5000) -> Dict[str, Any]:
        """Waits for element or event."""
        args = ["wait", "--timeout", str(timeout_ms)]
        if element_ref:
            args.extend(["--element", element_ref.strip("'\""), "--predicate", "actionable"])
        return self.run_cmd(args, timeout=(timeout_ms // 1000) + 5)


_AGENT_DESKTOP_INSTANCE = AgentDesktop()

def get_agent_desktop() -> AgentDesktop:
    return _AGENT_DESKTOP_INSTANCE


def agent_desktop_control(parameters: Dict[str, Any], player=None) -> str:
    """
    Dispatches agent-desktop actions for J.A.R.V.I.S.
    """
    params = parameters or {}
    action = params.get("action", "").lower().strip()
    app = params.get("app", "")
    target = params.get("target") or params.get("ref") or params.get("name") or params.get("query", "")
    text = params.get("text", "")
    headed = params.get("headed", False)

    ad = get_agent_desktop()

    if player and hasattr(player, "write_log"):
        player.write_log(f"DESKTOP: agent-desktop -> {action} target='{target}' app='{app}'")

    try:
        # 1. Status / Diagnostics
        if action in ("status", "health"):
            res = ad.status()
            if res.get("ok"):
                data = res.get("data", {})
                plat = data.get("platform", "unknown")
                acc = data.get("permissions", {}).get("accessibility", {}).get("state", "unknown")
                return f"agent-desktop online (Platform: {plat}, Accessibility: {acc}, Version: {data.get('version')})."
            return f"agent-desktop status error: {res.get('error', {}).get('message')}"

        # 2. Snapshot
        elif action in ("snapshot", "inspect", "tree"):
            res = ad.snapshot(app=app or None, root_ref=target if target.startswith("@") else None)
            if res.get("ok"):
                raw = json.dumps(res.get("data", {}), indent=2)
                if len(raw) > 2500:
                    raw = raw[:2500] + "\n... [truncated for brevity]"
                return f"Desktop UI Snapshot ({app or 'Active Window'}):\n{raw}"
            err = res.get("error", {})
            return f"Snapshot failed: {err.get('code')} — {err.get('message')}"

        # 3. Find
        elif action in ("find", "search_element"):
            if not target:
                return "Please provide an element name, query, or text to find."
            res = ad.find(target, app=app or None, role=params.get("role"))
            if res.get("ok"):
                data = res.get("data", {})
                elements = data.get("elements", []) if isinstance(data, dict) else data
                if not elements:
                    return f"No matching UI elements found for '{target}'."
                lines = [f"Found {len(elements)} element(s) matching '{target}':"]
                for el in elements[:8]:
                    lines.append(f"• Ref: `{el.get('ref')}` | Role: {el.get('role')} | Name: '{el.get('name')}'")
                return "\n".join(lines)
            err = res.get("error", {})
            return f"Find failed: {err.get('code')} — {err.get('message')}"

        # 4. Click
        elif action in ("click", "press_element"):
            if not target:
                return "Please provide a @ref ID or element name to click."

            # If user passed text instead of @ref, search first
            ref = target
            if not ref.startswith("@"):
                find_res = ad.find(target, app=app or None)
                if find_res.get("ok"):
                    data = find_res.get("data", {})
                    els = data.get("elements", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                    if els:
                        ref = els[0].get("ref", "")
                    else:
                        return f"Could not find any UI element named '{target}' to click."
                else:
                    return f"Element search error: {find_res.get('error', {}).get('message')}"

            res = ad.click(ref, headed=headed)
            if res.get("ok"):
                return f"Successfully clicked element `{ref}` ({target})."
            err = res.get("error", {})
            return f"Click failed on `{ref}`: {err.get('code')} — {err.get('message')}"

        # 5. Type
        elif action in ("type", "write", "fill"):
            if not target:
                return "Please provide a @ref ID or element name to type into."
            ref = target
            if not ref.startswith("@"):
                find_res = ad.find(target, app=app or None)
                if find_res.get("ok"):
                    data = find_res.get("data", {})
                    els = data.get("elements", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                    if els:
                        ref = els[0].get("ref", "")
                    else:
                        return f"Could not find UI field '{target}' to type into."
                else:
                    return f"Element search error: {find_res.get('error', {}).get('message')}"

            res = ad.type_text(ref, text)
            if res.get("ok"):
                return f"Typed '{text}' into element `{ref}`."
            err = res.get("error", {})
            return f"Type failed on `{ref}`: {err.get('code')} — {err.get('message')}"

        # 6. Key Combo Press
        elif action in ("press", "key", "hotkey"):
            key_combo = target or params.get("keys") or params.get("key", "return")
            res = ad.press(key_combo)
            if res.get("ok"):
                return f"Pressed key combo: {key_combo}"
            err = res.get("error", {})
            return f"Press failed: {err.get('code')} — {err.get('message')}"

        # 7. Focus Window
        elif action in ("focus_window", "focus"):
            win_target = target or app
            if not win_target:
                return "Please provide a window title or app name to focus."
            res = ad.focus_window(win_target)
            if res.get("ok"):
                return f"Focused window for '{win_target}'."
            err = res.get("error", {})
            return f"Focus failed: {err.get('code')} — {err.get('message')}"

        # 8. Launch App
        elif action in ("launch", "open_app"):
            app_to_launch = target or app
            if not app_to_launch:
                return "Please provide an application name to launch."
            res = ad.launch(app_to_launch)
            if res.get("ok"):
                return f"Launched application '{app_to_launch}'."
            err = res.get("error", {})
            return f"Launch failed: {err.get('code')} — {err.get('message')}"

        # 9. List Apps / Windows
        elif action in ("list_apps", "apps"):
            res = ad.list_apps()
            if res.get("ok"):
                apps_list = res.get("data", {}).get("apps", [])
                if not apps_list:
                    return "No running GUI applications detected."
                return "Running GUI applications:\n• " + "\n• ".join(apps_list[:15])
            return f"List apps failed: {res.get('error', {}).get('message')}"

        elif action in ("list_windows", "windows"):
            res = ad.list_windows(app=app or None)
            if res.get("ok"):
                wins = res.get("data", [])
                if not wins:
                    return "No visible windows found."
                lines = ["Visible Windows:"]
                for w in wins[:10]:
                    title = w.get("title") or w.get("name") or "Untitled"
                    lines.append(f"• [{w.get('app', 'App')}] {title}")
                return "\n".join(lines)
            return f"List windows failed: {res.get('error', {}).get('message')}"

        # 10. Scroll
        elif action == "scroll":
            direction = params.get("direction", "down")
            amount = int(params.get("amount", 3))
            res = ad.scroll(ref=target if target.startswith("@") else None, direction=direction, amount=amount)
            if res.get("ok"):
                return f"Scrolled {direction} by {amount}."
            return f"Scroll failed: {res.get('error', {}).get('message')}"

        else:
            return f"Unknown agent-desktop action: '{action}'. Available: status, snapshot, find, click, type, press, focus_window, launch, scroll, list_apps, list_windows."

    except Exception as e:
        return f"agent_desktop_control error: {e}"
