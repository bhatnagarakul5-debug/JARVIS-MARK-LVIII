from __future__ import annotations

import json
import math
import os
import platform
import random
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

from PyQt6.QtCore import (
    QEasingCurve, QMimeData, QObject, QPointF, QRectF, QSize, Qt,
    QTimer, QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QDragEnterEvent, QDropEvent, QFont, QFontDatabase,
    QImage, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient, QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QScrollArea, QSizePolicy, QTextEdit,
    QVBoxLayout, QWidget, QProgressBar, QGraphicsBlurEffect,
)

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR   = _base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"

_DEFAULT_W, _DEFAULT_H = 980, 700
_MIN_W,     _MIN_H     = 820, 580
_LEFT_W  = 168
_RIGHT_W = 340

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"


class C:
    BG        = "#040b14"
    PANEL     = "#09172a"
    PANEL2    = "#0e2038"
    BORDER    = "#00d4ff"
    BORDER_B  = "#00f0ff"
    BORDER_A  = "#0088b3"
    PRI       = "#00f0ff"
    PRI_DIM   = "#0088aa"
    PRI_GHO   = "#06283d"
    ACC       = "#ff6600"
    ACC2      = "#ffcc00"
    GREEN     = "#00ffaa"
    GREEN_D   = "#00bb77"
    RED       = "#ff0055"
    MUTED_C   = "#ff3366"
    TEXT      = "#e0f8ff"
    TEXT_DIM  = "#5aa8c0"
    TEXT_MED  = "#80d8ec"
    WHITE     = "#ffffff"
    DARK      = "#050f1e"
    BAR_BG    = "#081628"

    # Emotional Spectrum Palette (Positive, Tactical, Sparring & Negative)
    EMO_EMPATHY     = "#9d72ff"
    EMO_TACTICAL    = "#00f0ff"
    EMO_WITTY       = "#ffaa00"
    EMO_MOTIVATE    = "#ff4422"
    EMO_COUNTER     = "#00e676"
    EMO_VIGILANT    = "#e02050"
    EMO_FRUSTRATED  = "#ff5722"
    EMO_SKEPTICAL   = "#d4a017"
    EMO_SOLEMN      = "#5c6bc0"
    EMO_CONCERNED   = "#ffb300"
    EMO_INDIGNANT   = "#e91e63"
    EMO_COLD        = "#90a4ae"


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h); c.setAlpha(a); return c

class _SysMetrics:
    def __init__(self):
        self.cpu  = 0.0
        self.mem  = 0.0
        self.net  = 0.0   
        self.gpu  = -1.0  
        self.tmp  = -1.0  
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._last_gpu_t = 0.0
        self._cached_gpu = -1.0
        self._last_tmp_t = 0.0
        self._cached_tmp = -1.0
        self._running = True
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _loop(self):
        while self._running:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(1.5)

    def _update(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent

        nc  = psutil.net_io_counters()
        now = time.time()
        dt  = now - self._last_net_t
        if dt > 0:
            sent = (nc.bytes_sent - self._last_net.bytes_sent) / dt
            recv = (nc.bytes_recv - self._last_net.bytes_recv) / dt
            net  = (sent + recv) / (1024 * 1024)
        else:
            net = 0.0
        self._last_net   = nc
        self._last_net_t = now

        gpu = self._get_gpu()

        tmp = self._get_temp()

        with self._lock:
            self.cpu = cpu
            self.mem = mem
            self.net = net
            self.gpu = gpu
            self.tmp = tmp

    def _get_gpu(self) -> float:
        now = time.time()
        if now - self._last_gpu_t < 10.0 and self._cached_gpu != -1.0:
            return self._cached_gpu
        val = self._query_gpu()
        self._cached_gpu = val
        self._last_gpu_t = now
        return val

    def _query_gpu(self) -> float:
        # NVIDIA
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2
            )
            if r.returncode == 0:
                vals = [float(v.strip()) for v in r.stdout.strip().split("\n") if v.strip()]
                if vals:
                    return sum(vals) / len(vals)
        except Exception:
            pass

        # Intel GPU (Windows) — uses PowerShell + GPU engine counter
        if _OS == "Windows":
            try:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "(Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine | "
                     "Where-Object { $_.Name -like '*engtype_3D*' } | "
                     "Measure-Object -Property UtilizationPercentage -Average).Average"],
                    capture_output=True, text=True, timeout=3,
                    creationflags=0x08000000  # CREATE_NO_WINDOW
                )
                if r.returncode == 0 and r.stdout.strip():
                    val = float(r.stdout.strip())
                    if 0 <= val <= 100:
                        return val
            except Exception:
                pass

            # Intel GPU fallback — try Get-Counter
            try:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "(Get-Counter '\\GPU Engine(*)\\Utilization Percentage' -ErrorAction SilentlyContinue).CounterSamples | "
                     "Where-Object { $_.CookedValue -gt 0 } | "
                     "Measure-Object -Property CookedValue -Average | "
                     "Select-Object -ExpandProperty Average"],
                    capture_output=True, text=True, timeout=3,
                    creationflags=0x08000000
                )
                if r.returncode == 0 and r.stdout.strip():
                    val = float(r.stdout.strip())
                    if 0 <= val <= 100:
                        return val
            except Exception:
                pass

        # AMD (Linux)
        if _OS == "Linux":
            try:
                r = subprocess.run(
                    ["rocm-smi", "--showuse", "--csv"],
                    capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0:
                    for line in r.stdout.strip().split("\n"):
                        parts = line.split(",")
                        if len(parts) >= 2:
                            try:
                                return float(parts[1].strip().replace("%", ""))
                            except ValueError:
                                pass
            except Exception:
                pass

            # Intel GPU (Linux)
            try:
                r = subprocess.run(
                    ["intel_gpu_top", "-J", "-s", "500"],
                    capture_output=True, text=True, timeout=1
                )
                if r.returncode == 0 and "Render/3D" in r.stdout:
                    import re
                    m = re.search(r'"busy":\s*([\d.]+)', r.stdout)
                    if m:
                        return float(m.group(1))
            except Exception:
                pass

        # macOS — powermetrics (GPU Engine)
        if _OS == "Darwin":
            try:
                r = subprocess.run(
                    ["sudo", "-n", "powermetrics", "-n", "1", "-i", "500",
                     "--samplers", "gpu_power"],
                    capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0 and "GPU" in r.stdout:
                    import re
                    m = re.search(r'GPU\s+Active:\s+([\d.]+)%', r.stdout)
                    if m:
                        return float(m.group(1))
            except Exception:
                pass

        return -1.0

    def _get_temp(self) -> float:
        now = time.time()
        if now - self._last_tmp_t < 10.0 and self._cached_tmp != -1.0:
            return self._cached_tmp
        val = self._query_temp()
        self._cached_tmp = val
        self._last_tmp_t = now
        return val

    def _query_temp(self) -> float:
        try:
            temps = psutil.sensors_temperatures()
            candidates = ["coretemp", "k10temp", "cpu_thermal", "acpitz",
                          "cpu-thermal", "zenpower", "it8688"]
            for name in candidates:
                if name in temps:
                    entries = temps[name]
                    if entries:
                        return entries[0].current
            for entries in temps.values():
                if entries:
                    return entries[0].current
        except Exception:
            pass
        if _OS == "Darwin":
            try:
                r = subprocess.run(
                    ["osx-cpu-temp"], capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0:
                    import re
                    m = re.search(r"([\d.]+)", r.stdout)
                    if m:
                        return float(m.group(1))
            except Exception:
                pass

        if _OS == "Windows":
            try:
                r = subprocess.run(
                    ["powershell", "-Command",
                     "(Get-WmiObject MSAcpi_ThermalZoneTemperature -Namespace root/wmi).CurrentTemperature"],
                    capture_output=True, text=True, timeout=3
                )
                if r.returncode == 0 and r.stdout.strip():
                    raw = float(r.stdout.strip().split("\n")[0])
                    return (raw / 10.0) - 273.15
            except Exception:
                pass

        return -1.0

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu,
                "mem": self.mem,
                "net": self.net,
                "gpu": self.gpu,
                "tmp": self.tmp,
            }

    def stop(self):
        self._running = False


_metrics = _SysMetrics()

class HudCanvas(QWidget):
    def __init__(self, face_path: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.muted    = False
        self.speaking = False
        self.state    = "INITIALISING"

        self.emotion = "TACTICAL"
        self._target_aura_rgb = [0, 240, 255]
        self._current_aura_rgb = [0.0, 240.0, 255.0]

        self._tick       = 0
        self._scale      = 1.0
        self._tgt_scale  = 1.0
        self._halo       = 55.0
        self._tgt_halo   = 55.0
        self._last_t     = time.time()
        self._scan       = 0.0
        self._scan2      = 180.0
        self._rings      = [0.0, 120.0, 240.0]
        self._pulses: list[float] = [0.0, 50.0, 100.0]
        self._blink      = True
        self._blink_tick = 0
        self._particles: list[list[float]] = []
        self._face_px: QPixmap | None = None
        self._load_face(face_path)

        # Human Gestures & Dynamic Framerate Throttling
        self._gesture_name: str | None = None
        self._gesture_tick: int = 0
        self._gesture_offset_y: float = 0.0
        self._gesture_tilt_deg: float = 0.0
        self._gesture_scale_mod: float = 1.0
        self._fps: int = 60

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(16)

    def set_fps(self, fps: int):
        """Dynamically adjusts HUD render interval for hardware equilibrium & thermal management."""
        fps = max(10, min(60, fps))
        self._fps = fps
        self._tmr.setInterval(int(1000 / fps))

    def trigger_gesture(self, gesture_name: str):
        """Initiates a physical human-like reaction gesture on the HUD canvas."""
        self._gesture_name = gesture_name.lower().strip()
        self._gesture_tick = 0


    def _load_face(self, path: str):
        try:
            from PIL import Image, ImageDraw
            import io
            img = Image.open(path).convert("RGBA")
            sz  = min(img.size)
            img = img.resize((sz, sz), Image.LANCZOS)
            mk  = Image.new("L", (sz, sz), 0)
            ImageDraw.Draw(mk).ellipse((2, 2, sz - 2, sz - 2), fill=255)
            img.putalpha(mk)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap(); px.loadFromData(buf.getvalue())
            self._face_px = px
        except Exception:
            self._face_px = None

    def _step(self):
        self._tick += 1
        now = time.time()
        if now - self._last_t > (0.12 if self.speaking else 0.5):
            if self.speaking:
                self._tgt_scale = random.uniform(1.06, 1.14)
                self._tgt_halo  = random.uniform(145, 190)
            elif self.muted:
                self._tgt_scale = random.uniform(0.998, 1.002)
                self._tgt_halo  = random.uniform(15, 28)
            else:
                self._tgt_scale = random.uniform(1.001, 1.008)
                self._tgt_halo  = random.uniform(48, 68)
            self._last_t = now

        sp = 0.38 if self.speaking else 0.15
        self._scale += (self._tgt_scale - self._scale) * sp
        self._halo  += (self._tgt_halo  - self._halo)  * sp

        speeds = [1.3, -0.9, 2.0] if self.speaking else [0.55, -0.35, 0.9]
        for i, spd in enumerate(speeds):
            self._rings[i] = (self._rings[i] + spd) % 360

        self._scan  = (self._scan  + (3.0 if self.speaking else 1.3)) % 360
        self._scan2 = (self._scan2 + (-2.0 if self.speaking else -0.75)) % 360

        fw  = min(self.width(), self.height())
        lim = fw * 0.74
        spd = 4.2 if self.speaking else 2.0
        self._pulses = [r + spd for r in self._pulses if r + spd < lim]
        if len(self._pulses) < 3 and random.random() < (0.07 if self.speaking else 0.025):
            self._pulses.append(0.0)

        if self.speaking and random.random() < 0.28:
            cx, cy = self.width() / 2, self.height() / 2
            ang = random.uniform(0, 2 * math.pi)
            r_s = fw * 0.28
            self._particles.append([
                cx + math.cos(ang) * r_s, cy + math.sin(ang) * r_s,
                math.cos(ang) * random.uniform(0.9, 2.4),
                math.sin(ang) * random.uniform(0.9, 2.4) - 0.4, 1.0,
            ])
        self._particles = [
            [p[0]+p[2], p[1]+p[3], p[2]*0.97, p[3]*0.97, p[4]-0.028]
            for p in self._particles if p[4] > 0
        ]

        self._blink_tick += 1
        if self._blink_tick >= 38:
            self._blink = not self._blink
            self._blink_tick = 0

        # Smooth aura color transition
        for i in range(3):
            self._current_aura_rgb[i] += (self._target_aura_rgb[i] - self._current_aura_rgb[i]) * 0.12

        # Process human gesture animation physics
        if self._gesture_name:
            self._gesture_tick += 1
            t = self._gesture_tick
            g = self._gesture_name

            if g == "sneeze":
                if t <= 6:
                    # Inward compression tensing
                    self._gesture_scale_mod = 1.0 - (t / 6.0) * 0.16
                    self._gesture_offset_y = -(t * 0.9)
                elif t == 7:
                    # Explosive sneeze burst!
                    self._gesture_scale_mod = 1.34
                    self._gesture_offset_y = 9.0
                    p_cx, p_cy = self.width() / 2, self.height() / 2
                    for _ in range(16):
                        ang = random.uniform(0, 2 * math.pi)
                        spd = random.uniform(2.5, 6.0)
                        self._particles.append([
                            p_cx, p_cy,
                            math.cos(ang) * spd, math.sin(ang) * spd,
                            1.2
                        ])
                elif t <= 22:
                    prog = (t - 7) / 15.0
                    damp = math.exp(-3.0 * prog) * math.cos(prog * math.pi * 3)
                    self._gesture_scale_mod = 1.0 + 0.34 * damp
                    self._gesture_offset_y = 9.0 * damp
                else:
                    self._gesture_scale_mod = 1.0
                    self._gesture_offset_y = 0.0
                    self._gesture_name = None

            elif g in ("cough", "throat_clear"):
                if t <= 4:
                    self._gesture_offset_y = 5.0 * (t / 4.0)
                elif t <= 8:
                    self._gesture_offset_y = -3.0 * ((8 - t) / 4.0)
                elif t <= 12:
                    self._gesture_offset_y = 3.5 * ((t - 8) / 4.0)
                elif t <= 16:
                    self._gesture_offset_y = -1.5 * ((16 - t) / 4.0)
                else:
                    self._gesture_offset_y = 0.0
                    self._gesture_name = None

            elif g in ("eyebrow", "smirk"):
                if t <= 6:
                    self._gesture_tilt_deg = 14.0 * (t / 6.0)
                elif t <= 20:
                    self._gesture_tilt_deg = 14.0
                elif t <= 28:
                    self._gesture_tilt_deg = 14.0 * (1.0 - (t - 20) / 8.0)
                else:
                    self._gesture_tilt_deg = 0.0
                    self._gesture_name = None

            elif g in ("yawn", "sigh"):
                if t <= 18:
                    self._gesture_scale_mod = 1.0 + 0.14 * (t / 18.0)
                elif t <= 36:
                    self._gesture_scale_mod = 1.14 - 0.14 * ((t - 18) / 18.0)
                else:
                    self._gesture_scale_mod = 1.0
                    self._gesture_name = None

            elif g == "blink":
                if t <= 5:
                    self._gesture_scale_mod = 1.0 - 0.35 * (t / 5.0)
                elif t <= 10:
                    self._gesture_scale_mod = 0.65 + 0.35 * ((t - 5) / 5.0)
                else:
                    self._gesture_scale_mod = 1.0
                    self._gesture_name = None

            elif g == "chuckle":
                if t <= 18:
                    self._gesture_offset_y = math.sin(t * 1.8) * 2.5
                else:
                    self._gesture_offset_y = 0.0
                    self._gesture_name = None

        self.update()

    def get_aura_color(self, alpha: int = 255) -> QColor:
        if self.muted:
            return qcol(C.MUTED_C, alpha)
        r = max(0, min(255, int(self._current_aura_rgb[0])))
        g = max(0, min(255, int(self._current_aura_rgb[1])))
        b = max(0, min(255, int(self._current_aura_rgb[2])))
        return QColor(r, g, b, max(0, min(255, alpha)))

    def set_emotion(self, emotion: str, color_hex: str = None):
        self.emotion = emotion.upper()
        if not color_hex:
            palette = {
                "EMPATHETIC": C.EMO_EMPATHY,
                "TACTICAL": C.EMO_TACTICAL,
                "WITTY": C.EMO_WITTY,
                "MOTIVATIONAL": C.EMO_MOTIVATE,
                "CHALLENGING": C.EMO_COUNTER,
                "VIGILANT": C.EMO_VIGILANT,
                "FRUSTRATED": C.EMO_FRUSTRATED,
                "SKEPTICAL": C.EMO_SKEPTICAL,
                "SOLEMN": C.EMO_SOLEMN,
                "CONCERNED": C.EMO_CONCERNED,
                "INDIGNANT": C.EMO_INDIGNANT,
                "COLD": C.EMO_COLD,
                "ULTRON_PRIME": "#ff1e1e",
            }
            color_hex = palette.get(self.emotion, C.PRI)
        c = QColor(color_hex)
        self._target_aura_rgb = [c.red(), c.green(), c.blue()]

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), qcol(C.BG))

        W, H = self.width(), self.height()
        cx, cy = W / 2, (H / 2) + self._gesture_offset_y
        fw = min(W, H)
        eff_scale = self._scale * self._gesture_scale_mod

        has_tilt = (self._gesture_tilt_deg != 0.0)
        if has_tilt:
            p.save()
            p.translate(cx, cy)
            p.rotate(self._gesture_tilt_deg)
            p.translate(-cx, -cy)

        # grid dots
        p.setPen(QPen(qcol(C.PRI_GHO), 1))
        for x in range(0, W, 48):
            for y in range(0, H, 48):
                p.drawPoint(x, y)

        r_face = fw * 0.31

        # halo glow
        for i in range(10):
            r   = r_face * (1.8 - i * 0.08)
            frc = 1.0 - i / 10
            a   = max(0, min(255, int(self._halo * 0.085 * frc)))
            col = self.get_aura_color(a)
            p.setPen(QPen(col, 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # pulse rings
        for pr in self._pulses:
            a   = max(0, int(230 * (1.0 - pr / (fw * 0.74))))
            col = self.get_aura_color(a)
            p.setPen(QPen(col, 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - pr, cy - pr, pr * 2, pr * 2))

        # spinning arc rings
        for idx, (r_frac, w_r, arc_l, gap) in enumerate(
            [(0.48, 3, 115, 78), (0.40, 2, 78, 55), (0.32, 1, 56, 40)]
        ):
            ring_r = fw * r_frac
            base   = self._rings[idx]
            a_val  = max(0, min(255, int(self._halo * (1.0 - idx * 0.18))))
            col    = self.get_aura_color(a_val)
            p.setPen(QPen(col, w_r)); p.setBrush(Qt.BrushStyle.NoBrush)
            angle = base
            rect  = QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
            while angle < base + 360:
                p.drawArc(rect, int(angle * 16), int(arc_l * 16))
                angle += arc_l + gap

        # scanners
        sr = fw * 0.50
        sa = min(255, int(self._halo * 1.5))
        ex = 75 if self.speaking else 44
        p.setPen(QPen(self.get_aura_color(sa), 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        srect = QRectF(cx - sr, cy - sr, sr * 2, sr * 2)
        p.drawArc(srect, int(self._scan * 16), int(ex * 16))
        p.setPen(QPen(qcol(C.ACC, sa // 2), 1.5))
        p.drawArc(srect, int(self._scan2 * 16), int(ex * 16))

        # tick marks
        t_out, t_in = fw * 0.497, fw * 0.474
        p.setPen(QPen(self.get_aura_color(140), 1))
        for deg in range(0, 360, 10):
            rad = math.radians(deg)
            inn = t_in if deg % 30 == 0 else t_in + 6
            p.drawLine(
                QPointF(cx + t_out * math.cos(rad), cy - t_out * math.sin(rad)),
                QPointF(cx + inn  * math.cos(rad), cy - inn  * math.sin(rad)),
            )

        # crosshair
        ch_r, gap_h = fw * 0.51, fw * 0.16
        p.setPen(QPen(self.get_aura_color(int(self._halo * 0.5)), 1))
        p.drawLine(QPointF(cx - ch_r, cy), QPointF(cx - gap_h, cy))
        p.drawLine(QPointF(cx + gap_h, cy), QPointF(cx + ch_r, cy))
        p.drawLine(QPointF(cx, cy - ch_r), QPointF(cx, cy - gap_h))
        p.drawLine(QPointF(cx, cy + gap_h), QPointF(cx, cy + ch_r))

        # corner brackets
        bl = 24
        bc = self.get_aura_color(210)
        hl, hr = cx - fw // 2, cx + fw // 2
        ht, hb = cy - fw // 2, cy + fw // 2
        p.setPen(QPen(bc, 2))
        for bx, by, dx, dy in [(hl,ht,1,1),(hr,ht,-1,1),(hl,hb,1,-1),(hr,hb,-1,-1)]:
            p.drawLine(QPointF(bx, by), QPointF(bx + dx * bl, by))
            p.drawLine(QPointF(bx, by), QPointF(bx, by + dy * bl))

        # face
        if self._face_px:
            fsz    = int(fw * 0.62 * eff_scale)
            scaled = self._face_px.scaled(
                fsz, fsz,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.drawPixmap(int(cx - fsz / 2), int(cy - fsz / 2), scaled)
        else:
            orb_r = int(fw * 0.27 * eff_scale)
            if self.muted:
                oc = (200, 0, 50)
            else:
                oc = (int(self._current_aura_rgb[0] * 0.4), int(self._current_aura_rgb[1] * 0.4), int(self._current_aura_rgb[2] * 0.4))
            for i in range(8, 0, -1):
                r2  = int(orb_r * i / 8)
                frc = i / 8
                a   = max(0, min(255, int(self._halo * 1.1 * frc)))
                p.setBrush(QBrush(QColor(int(oc[0]*frc), int(oc[1]*frc), int(oc[2]*frc), a)))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QRectF(cx - r2, cy - r2, r2 * 2, r2 * 2))
            p.setPen(QPen(self.get_aura_color(min(255, int(self._halo * 2))), 1))
            p.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
            core_title = "U.L.T.R.O.N" if "ULTRON" in self.emotion else "J.A.R.V.I.S"
            p.drawText(QRectF(cx - 80, cy - 14, 160, 28),
                       Qt.AlignmentFlag.AlignCenter, core_title)

        # particles
        for pt in self._particles:
            a = max(0, min(255, int(pt[4] * 255)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(self.get_aura_color(a)))
            p.drawEllipse(QPointF(pt[0], pt[1]), 2.5, 2.5)

        # status text
        sy = cy + fw * 0.40
        if self.muted:
            txt, col = "⊘  MUTED",     qcol(C.MUTED_C)
        elif self.speaking:
            txt, col = "●  SPEAKING",  qcol(C.ACC)
        elif self.state == "THINKING":
            sym = "◈" if self._blink else "◇"
            txt, col = f"{sym}  THINKING",   qcol(C.ACC2)
        elif self.state == "PROCESSING":
            sym = "▷" if self._blink else "▶"
            txt, col = f"{sym}  PROCESSING", qcol(C.ACC2)
        elif self.state == "LISTENING":
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  LISTENING",  qcol(C.GREEN)
        else:
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  {self.state}", self.get_aura_color(255)

        p.setPen(QPen(col, 1))
        p.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        p.drawText(QRectF(0, sy, W, 26), Qt.AlignmentFlag.AlignCenter, txt)

        # 32-Bar High-Definition Glass Equalizer Visualizer
        wy = sy + 32
        N, bw = 32, 9
        wx0 = (W - N * bw) / 2
        
        for i in range(N):
            if self.muted:
                hgt, cl = 3, qcol(C.RED)
            elif self.speaking:
                hgt = random.randint(4, 28)
                cl  = self.get_aura_color(255) if hgt > 16 else qcol(C.GREEN)
            elif self.state == "THINKING":
                hgt = int(8 + 6 * math.sin(self._tick * 0.15 + i * 0.4))
                cl  = qcol(C.ACC2)
            else:
                hgt = int(4 + 4 * math.sin(self._tick * 0.08 + i * 0.5))
                cl  = qcol(C.BORDER_B)

            # Glass Bar Fill
            bar_rect = QRectF(wx0 + i * bw, wy + 30 - hgt, bw - 2, hgt)
            p.setBrush(QBrush(cl))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(bar_rect, 2, 2)

            # Glowing Peak Indicator Dot
            if hgt > 8:
                peak_y = wy + 30 - hgt - 3
                p.setBrush(QBrush(qcol(C.WHITE if self.speaking else C.PRI)))
                p.drawEllipse(QPointF(wx0 + i * bw + (bw - 2) / 2, peak_y), 1.5, 1.5)

        # Emotional Spectrum & Gesture Telemetry Indicators
        badge_y = wy + 42
        p.setPen(QPen(self.get_aura_color(180), 1))
        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        gesture_suffix = f" | GESTURE: {self._gesture_name.upper()}" if self._gesture_name else ""
        p.drawText(QRectF(0, badge_y, W, 20), Qt.AlignmentFlag.AlignCenter, f"◆ SPECTRUM: {self.emotion}{gesture_suffix}")

        if has_tilt:
            p.restore()

class MetricBar(QWidget):

    def __init__(self, label: str, color: str = C.PRI, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._value = 0.0       # 0–100
        self._text  = "--"
        self.setFixedHeight(38)
        self.setMinimumWidth(80)

    def set_value(self, pct: float, text: str):
        self._value = max(0.0, min(100.0, pct))
        self._text  = text
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        p.setBrush(QBrush(qcol(C.PANEL2, 220)))
        p.setPen(QPen(qcol(C.BORDER_B, 220), 1.2))
        p.drawRoundedRect(QRectF(1, 1, W - 2, H - 2), 6, 6)

        bar_h   = 4
        bar_y   = H - bar_h - 5
        bar_w   = W - 12
        bar_x   = 6
        fill_w  = int(bar_w * self._value / 100)

        p.setBrush(QBrush(qcol(C.BAR_BG)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 2, 2)

        if self._value > 85:
            bar_col = qcol(C.RED)
        elif self._value > 65:
            bar_col = qcol(C.ACC)
        else:
            bar_col = qcol(self._color)

        if fill_w > 0:
            p.setBrush(QBrush(bar_col))
            p.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h), 2, 2)

        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(8, 5, 50, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(bar_col if self._text != "--" else qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(0, 4, W - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._text)

class LogWidget(QTextEdit):
    _sig = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Courier New", 9))
        self.setStyleSheet(f"""
            QTextEdit {{
                background: {C.PANEL2};
                color: {C.TEXT};
                border: 1.5px solid {C.BORDER_B};
                border-radius: 6px;
                padding: 6px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{
                background: {C.BG};
                width: 8px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.PRI};
                border-radius: 4px;
                min-height: 20px;
            }}
        """)
        self._queue: list[str] = []
        self._typing  = False
        self._text    = ""
        self._pos     = 0
        self._tag     = "sys"
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._sig.connect(self._enqueue)

    def append_log(self, text: str):
        self._sig.emit(text)

    def _enqueue(self, text: str):
        self._queue.append(text)
        if not self._typing:
            self._next()

    def _next(self):
        if not self._queue:
            self._typing = False
            return
        self._typing = True
        self._text   = self._queue.pop(0)
        self._pos    = 0
        tl = self._text.lower()
        if   tl.startswith("you:"):    self._tag = "you"
        elif tl.startswith("jarvis:"): self._tag = "ai"
        elif tl.startswith("file:"):   self._tag = "file"
        elif "err" in tl:              self._tag = "err"
        else:                          self._tag = "sys"
        self._tmr.start(6)

    def _step(self):
        if self._pos < len(self._text):
            ch  = self._text[self._pos]
            cur = self.textCursor()
            fmt = cur.charFormat()
            col = {
                "you":  qcol(C.WHITE),
                "ai":   qcol(C.PRI),
                "err":  qcol(C.RED),
                "file": qcol(C.GREEN),
                "sys":  qcol(C.ACC2),
            }.get(self._tag, qcol(C.TEXT))
            fmt.setForeground(QBrush(col))
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText(ch, fmt)
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            self._pos += 1
        else:
            self._tmr.stop()
            cur = self.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText("\n")
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            QTimer.singleShot(20, self._next)

_FILE_ICONS = {
    "image":   ("🖼", "#00d4ff"), "video":   ("🎬", "#ff6b00"),
    "audio":   ("🎵", "#cc44ff"), "pdf":     ("📄", "#ff4444"),
    "word":    ("📝", "#4488ff"), "excel":   ("📊", "#44bb44"),
    "code":    ("💻", "#ffcc00"), "archive": ("📦", "#ff8844"),
    "pptx":    ("📊", "#ff6622"), "text":    ("📃", "#aaaaaa"),
    "data":    ("🔧", "#88ddff"), "unknown": ("📎", "#888888"),
}
_EXT_TO_CAT = {
    **dict.fromkeys(["jpg","jpeg","png","gif","webp","bmp","tiff","svg","ico"], "image"),
    **dict.fromkeys(["mp4","avi","mov","mkv","wmv","flv","webm","m4v"],         "video"),
    **dict.fromkeys(["mp3","wav","ogg","m4a","aac","flac","wma","opus"],        "audio"),
    **dict.fromkeys(["pdf"],                                                     "pdf"),
    **dict.fromkeys(["doc","docx"],                                              "word"),
    **dict.fromkeys(["xls","xlsx","ods"],                                        "excel"),
    **dict.fromkeys(["ppt","pptx"],                                              "pptx"),
    **dict.fromkeys(["py","js","ts","jsx","tsx","html","css","java","c","cpp",
                     "cs","go","rs","rb","php","swift","kt","sh","sql","lua"],   "code"),
    **dict.fromkeys(["zip","rar","tar","gz","7z","bz2","xz"],                   "archive"),
    **dict.fromkeys(["txt","md","rst","log"],                                    "text"),
    **dict.fromkeys(["csv","tsv","json","xml"],                                  "data"),
}

def _file_category(path: Path) -> str:
    return _EXT_TO_CAT.get(path.suffix.lower().lstrip("."), "unknown")

def _fmt_size(size: int) -> str:
    if   size < 1024:    return f"{size} B"
    elif size < 1024**2: return f"{size/1024:.1f} KB"
    elif size < 1024**3: return f"{size/1024**2:.1f} MB"
    else:                return f"{size/1024**3:.1f} GB"


class FileDropZone(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(100)
        self._current_file: str | None = None
        self._hovering  = False
        self._drag_over = False
        self._dash_offset = 0.0
        self._anim_tmr = QTimer(self)
        self._anim_tmr.timeout.connect(self._animate)
        self._anim_tmr.start(40)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._canvas = _DropCanvas(self)
        layout.addWidget(self._canvas)

    def _animate(self):
        self._dash_offset = (self._dash_offset + 0.8) % 20
        self._canvas.update()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag_over = True; self._canvas.update()

    def dragLeaveEvent(self, e):
        self._drag_over = False; self._canvas.update()

    def dropEvent(self, e: QDropEvent):
        self._drag_over = False
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_file():
                self._set_file(path)
        self._canvas.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._browse()

    def enterEvent(self, e):
        self._hovering = True; self._canvas.update()

    def leaveEvent(self, e):
        self._hovering = False; self._canvas.update()

    def current_file(self) -> str | None:
        return self._current_file

    def clear_file(self):
        self._current_file = None; self._canvas.update()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a file for JARVIS", str(Path.home()),
            "All Files (*.*);;"
            "Images (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.svg);;"
            "Documents (*.pdf *.docx *.txt *.md *.pptx);;"
            "Data (*.csv *.xlsx *.json *.xml);;"
            "Code (*.py *.js *.ts *.html *.css *.java *.cpp *.go);;"
            "Audio (*.mp3 *.wav *.ogg *.m4a *.aac *.flac);;"
            "Video (*.mp4 *.avi *.mov *.mkv *.wmv *.webm);;"
            "Archives (*.zip *.rar *.tar *.gz *.7z)",
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._current_file = path
        self._canvas.update()
        self.file_selected.emit(path)


class _DropCanvas(QWidget):
    def __init__(self, zone: FileDropZone):
        super().__init__(zone)
        self._z = zone

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        z    = self._z
        W, H = self.width(), self.height()
        pad  = 6
        rect = QRectF(pad, pad, W - pad * 2, H - pad * 2)

        bg_col = qcol("#001a24" if z._drag_over else ("#001218" if z._hovering else C.PANEL))
        p.setBrush(QBrush(bg_col)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   border_col = qcol(C.GREEN, 200)
        elif z._drag_over:    border_col = qcol(C.PRI, 230)
        elif z._hovering:     border_col = qcol(C.BORDER_B, 200)
        else:                 border_col = qcol(C.BORDER, 160)

        pen = QPen(border_col, 1.5, Qt.PenStyle.DashLine)
        pen.setDashOffset(z._dash_offset)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   self._paint_file(p, W, H)
        elif z._drag_over:    self._paint_drag_over(p, W, H)
        else:                 self._paint_idle(p, W, H, z._hovering)

    def _paint_idle(self, p, W, H, hover):
        cx, cy = W / 2, H / 2
        col = qcol(C.PRI_DIM if not hover else C.PRI)
        p.setPen(QPen(col, 2)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(cx, cy - 14), QPointF(cx, cy + 4))
        p.drawLine(QPointF(cx - 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx + 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx - 14, cy + 4), QPointF(cx + 14, cy + 4))
        p.setFont(QFont("Courier New", 8))
        p.setPen(QPen(qcol(C.PRI_DIM if not hover else C.TEXT), 1))
        p.drawText(QRectF(0, cy + 8, W, 16), Qt.AlignmentFlag.AlignCenter,
                   "Drop file here  or  Click to Browse")
        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol("#1a4a5a"), 1))
        p.drawText(QRectF(0, cy + 24, W, 14), Qt.AlignmentFlag.AlignCenter,
                   "Images · Video · Audio · PDF · Docs · Code · Data")

    def _paint_drag_over(self, p, W, H):
        cx, cy = W / 2, H / 2
        p.setFont(QFont("Courier New", 20))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy - 24, W, 32), Qt.AlignmentFlag.AlignCenter, "⬇")
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy + 12, W, 16), Qt.AlignmentFlag.AlignCenter, "Release to load")

    def _paint_file(self, p, W, H):
        path = Path(self._z._current_file)
        cat  = _file_category(path)
        icon, icon_col = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size_str = _fmt_size(path.stat().st_size)
        ext_str  = path.suffix.upper().lstrip(".") or "FILE"

        block_x, block_w = 10, 60
        p.setFont(QFont("Segoe UI Emoji", 22) if _OS == "Windows" else QFont("Arial", 22))
        p.setPen(QPen(qcol(icon_col), 1))
        p.drawText(QRectF(block_x, 0, block_w, H), Qt.AlignmentFlag.AlignCenter, icon)

        tx = block_x + block_w + 6
        tw = W - tx - 38

        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.WHITE), 1))
        name = path.name if len(path.name) <= 34 else path.name[:31] + "..."
        p.drawText(QRectF(tx, H * 0.18, tw, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)

        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(tx, H * 0.18 + 18, tw, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{ext_str}  ·  {size_str}")

        p.setFont(QFont("Courier New", 6))
        p.setPen(QPen(qcol("#1e5c6a"), 1))
        par = str(path.parent)
        if len(par) > 42: par = "…" + par[-41:]
        p.drawText(QRectF(tx, H * 0.18 + 34, tw, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, par)

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.RED, 180), 1))
        p.drawText(QRectF(W - 34, 0, 28, H), Qt.AlignmentFlag.AlignCenter, "✕")

    def mousePressEvent(self, e):
        z = self._z
        if z._current_file and e.pos().x() > self.width() - 34:
            z.clear_file()
        else:
            z.mousePressEvent(e)


_cv2_module = None

def _get_cv2():
    global _cv2_module
    if _cv2_module is None:
        try:
            import cv2
            _cv2_module = cv2
        except Exception:
            _cv2_module = False
    return _cv2_module if _cv2_module is not False else None


class CameraPreviewWidget(QWidget):
    """Futuristic HUD Camera preview widget that displays live OpenCV feed when camera is ON."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(120)
        self.setMinimumWidth(120)
        self.pixmap: QPixmap | None = None
        self.is_on = False

    def update_frame(self, cv_frame):
        try:
            cv2 = _get_cv2()
            if cv2 is None:
                return
            h, w, ch = cv_frame.shape
            bytes_per_line = ch * w
            rgb = cv2.cvtColor(cv_frame, cv2.COLOR_BGR2RGB)
            qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            self.pixmap = QPixmap.fromImage(qimg)
            self.is_on = True
            self.update()
        except Exception:
            pass

    def set_offline(self):
        self.is_on = False
        self.pixmap = None
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        p.setBrush(QBrush(qcol(C.PANEL2)))
        p.setPen(QPen(qcol(C.BORDER_A if not self.is_on else C.GREEN), 1))
        p.drawRoundedRect(QRectF(1, 1, W - 2, H - 2), 4, 4)

        if self.is_on and self.pixmap and not self.pixmap.isNull():
            scaled = self.pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(0, 0, scaled)
            
            # HUD Tag
            p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            p.setPen(QPen(qcol(C.GREEN)))
            p.drawText(QRectF(6, 4, W - 12, 14), Qt.AlignmentFlag.AlignLeft, "● LIVE SCAN")
        else:
            # Offline State
            p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            p.setPen(QPen(qcol(C.TEXT_DIM)))
            p.drawText(QRectF(0, 0, W, H), Qt.AlignmentFlag.AlignCenter, "📷 CAMERA OFFLINE\n[F6 TO TOGGLE]")


class SetupOverlay(QWidget):
    done = pyqtSignal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SetupOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)

        detected = {"darwin": "mac", "windows": "windows"}.get(
            _OS.lower(), "linux"
        )
        self._sel_os = detected

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 22, 30, 22)
        layout.setSpacing(8)

        def _lbl(txt, font_size=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Courier New", font_size,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        layout.addWidget(_lbl("◈  INITIALISATION REQUIRED", 13, True))
        layout.addWidget(_lbl("Configure J.A.R.V.I.S. before first boot.", 9, color=C.PRI_DIM))
        layout.addSpacing(6)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep)
        layout.addSpacing(4)

        layout.addWidget(_lbl("GEMINI API KEY", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("AIza…")
        self._key_input.setFont(QFont("Courier New", 10))
        self._key_input.setFixedHeight(32)
        self._key_input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        layout.addWidget(self._key_input)
        layout.addSpacing(8)

        layout.addWidget(_lbl("OPENROUTER API KEY", 8, color=C.TEXT_DIM,
                       align=Qt.AlignmentFlag.AlignLeft))
        self._or_input = QLineEdit()
        self._or_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._or_input.setPlaceholderText("sk-or-…")
        self._or_input.setFont(QFont("Courier New", 10))
        self._or_input.setFixedHeight(32)
        self._or_input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.ACC2}; }}
        """)
        layout.addWidget(self._or_input)

        layout.addSpacing(12)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep2)
        layout.addSpacing(4)

        layout.addWidget(_lbl("OPERATING SYSTEM", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        det_name = {"windows": "Windows", "mac": "macOS", "linux": "Linux"}[detected]
        layout.addWidget(_lbl(f"Auto-detected: {det_name}", 8, color=C.ACC2,
                               align=Qt.AlignmentFlag.AlignLeft))

        os_row = QHBoxLayout(); os_row.setSpacing(6)
        self._os_btns: dict[str, QPushButton] = {}
        for key, label in [("windows","⊞  Windows"),("mac","  macOS"),("linux","🐧  Linux")]:
            btn = QPushButton(label)
            btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._sel(k))
            os_row.addWidget(btn)
            self._os_btns[key] = btn
        layout.addLayout(os_row)
        self._sel(detected)
        layout.addSpacing(12)

        init_btn = QPushButton("▸  INITIALISE SYSTEMS")
        init_btn.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        init_btn.setFixedHeight(36)
        init_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        init_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C.PRI_GHO}; border: 1px solid {C.PRI};
            }}
        """)
        init_btn.clicked.connect(self._submit)
        layout.addWidget(init_btn)

    def _sel(self, key: str):
        self._sel_os = key
        pal = {"windows":(C.PRI,"#001a22"),"mac":(C.ACC2,"#1a1400"),"linux":(C.GREEN,"#001a0d")}
        for k, btn in self._os_btns.items():
            if k == key:
                fg, bg = pal[k]
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {fg}; color: {bg};
                        border: none; border-radius: 3px; font-weight: bold;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: #000d12; color: {C.TEXT_DIM};
                        border: 1px solid {C.BORDER}; border-radius: 3px;
                    }}
                    QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
                """)

    def _submit(self):
        key = self._key_input.text().strip()
        or_key = self._or_input.text().strip()
        if not key:
            self._key_input.setStyleSheet(
                self._key_input.styleSheet() +
                f" QLineEdit {{ border: 1px solid {C.RED}; }}"
            )
            return
        if not or_key:
            self._or_input.setStyleSheet(
                self._or_input.styleSheet() +
                f" QLineEdit {{ border: 1px solid {C.RED}; }}"
            )
            return
        self.done.emit(key, or_key, self._sel_os)


class SettingsOverlay(QWidget):
    """In-app settings panel for customizing JARVIS without editing code."""
    settings_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SettingsOverlay {{
                background: rgba(0, 6, 10, 248);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)

        self._settings = self._load()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(6)

        def _lbl(txt, sz=9, bold=False, color=C.PRI, align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Courier New", sz, QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        # Header
        layout.addWidget(_lbl("⚙  JARVIS SETTINGS", 13, True))
        layout.addWidget(_lbl("Customize your assistant without editing code.", 8, color=C.PRI_DIM))
        layout.addSpacing(4)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep)
        layout.addSpacing(4)

        # Scroll area for settings fields
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{ background: {C.BG}; width: 6px; border: none; }}
            QScrollBar::handle:vertical {{ background: {C.BORDER_B}; border-radius: 3px; min-height: 16px; }}
        """)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        inner_lay = QVBoxLayout(inner)
        inner_lay.setContentsMargins(0, 0, 0, 0)
        inner_lay.setSpacing(8)

        self._fields = {}
        field_defs = [
            ("user_name",         "YOUR NAME",          "text"),
            ("voice_name",        "JARVIS VOICE",       "text"),
            ("address_style",     "ADDRESS STYLE",      "text"),
            ("personality",       "PERSONALITY",         "text"),
            ("language",          "LANGUAGE",            "text"),
            ("default_browser",   "DEFAULT BROWSER",    "text"),
            ("auto_memory",       "AUTO MEMORY",         "toggle"),
            ("speak_confirmations", "SPEAK CONFIRMATIONS", "toggle"),
        ]

        for key, label, ftype in field_defs:
            inner_lay.addWidget(_lbl(label, 7, color=C.TEXT_DIM, align=Qt.AlignmentFlag.AlignLeft))
            if ftype == "text":
                inp = QLineEdit(str(self._settings.get(key, "")))
                inp.setFont(QFont("Courier New", 9))
                inp.setFixedHeight(28)
                inp.setStyleSheet(f"""
                    QLineEdit {{
                        background: #000d12; color: {C.TEXT};
                        border: 1px solid {C.BORDER}; border-radius: 3px; padding: 3px 7px;
                    }}
                    QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
                """)
                inner_lay.addWidget(inp)
                self._fields[key] = inp
            elif ftype == "toggle":
                btn = QPushButton()
                val = self._settings.get(key, True)
                btn.setProperty("toggled", val)
                btn.setText("ON" if val else "OFF")
                btn.setFixedHeight(28)
                btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                self._style_toggle(btn, val)
                btn.clicked.connect(lambda _, b=btn, k=key: self._flip_toggle(b, k))
                inner_lay.addWidget(btn)
                self._fields[key] = btn

        inner_lay.addStretch()
        scroll.setWidget(inner)
        layout.addWidget(scroll, stretch=1)

        layout.addSpacing(6)
        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep2)
        layout.addSpacing(4)

        # Save + Close buttons
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)

        save_btn = QPushButton("💾  SAVE")
        save_btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        save_btn.setFixedHeight(32)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.GREEN};
                border: 1px solid {C.GREEN_D}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: #001a0d; border: 1px solid {C.GREEN}; }}
        """)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        close_btn = QPushButton("✕  CLOSE")
        close_btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        close_btn.setFixedHeight(32)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{ color: {C.RED}; border: 1px solid {C.RED}; }}
        """)
        close_btn.clicked.connect(self.hide)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

    def _style_toggle(self, btn, val):
        if val:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: #001a0d; color: {C.GREEN};
                    border: 1px solid {C.GREEN_D}; border-radius: 3px;
                }}
            """)
        else:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: #140006; color: {C.RED};
                    border: 1px solid {C.RED}; border-radius: 3px;
                }}
            """)

    def _flip_toggle(self, btn, key):
        cur = btn.property("toggled")
        nv = not cur
        btn.setProperty("toggled", nv)
        btn.setText("ON" if nv else "OFF")
        self._style_toggle(btn, nv)

    def _load(self) -> dict:
        path = _base_dir() / "config" / "jarvis_settings.json"
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {
            "user_name": "", "voice_name": "Charon", "address_style": "sir",
            "personality": "professional", "language": "English",
            "default_browser": "chrome", "auto_memory": True, "speak_confirmations": True,
        }

    def _save(self):
        data = dict(self._settings)
        for key, widget in self._fields.items():
            if isinstance(widget, QLineEdit):
                data[key] = widget.text().strip()
            elif isinstance(widget, QPushButton):
                data[key] = widget.property("toggled")
        path = _base_dir() / "config" / "jarvis_settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self._settings = data
        self.settings_changed.emit(data)
        self.hide()


class HistoryOverlay(QWidget):
    """In-app overlay for viewing and searching conversation history."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            HistoryOverlay {{
                background: rgba(0, 6, 10, 248);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(6)

        def _lbl(txt, sz=9, bold=False, color=C.PRI, align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Courier New", sz, QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        layout.addWidget(_lbl("📜  CONVERSATION HISTORY", 12, True))
        layout.addWidget(_lbl("Search or review past interactions", 8, color=C.PRI_DIM))
        layout.addSpacing(4)

        # Search bar
        self._search_in = QLineEdit()
        self._search_in.setPlaceholderText("Search history...")
        self._search_in.setFont(QFont("Courier New", 9))
        self._search_in.setFixedHeight(28)
        self._search_in.setStyleSheet(f"""
            QLineEdit {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 3px 7px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        self._search_in.textChanged.connect(self._do_search)
        layout.addWidget(self._search_in)

        # Scroll area for entries
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{ background: {C.BG}; width: 6px; border: none; }}
            QScrollBar::handle:vertical {{ background: {C.BORDER_B}; border-radius: 3px; min-height: 16px; }}
        """)
        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_lay = QVBoxLayout(self._list_widget)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(6)
        scroll.setWidget(self._list_widget)
        layout.addWidget(scroll, stretch=1)

        close_btn = QPushButton("✕  CLOSE")
        close_btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        close_btn.setFixedHeight(30)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{ color: {C.RED}; border: 1px solid {C.RED}; }}
        """)
        close_btn.clicked.connect(self.hide)
        layout.addWidget(close_btn)

        self._load_entries()

    def _load_entries(self, query: str = ""):
        # Clear existing
        while self._list_lay.count():
            child = self._list_lay.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        try:
            from memory.conversation_log import get_recent, search_history
            entries = search_history(query) if query else get_recent(25)
            if not entries:
                lbl = QLabel("No conversation history found.")
                lbl.setFont(QFont("Courier New", 8))
                lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
                self._list_lay.addWidget(lbl)
                return

            for item in reversed(entries):
                box = QWidget()
                box.setStyleSheet(f"background: {C.PANEL2}; border: 1px solid {C.BORDER_A}; border-radius: 3px; padding: 4px;")
                b_lay = QVBoxLayout(box)
                b_lay.setContentsMargins(6, 4, 6, 4)
                b_lay.setSpacing(2)

                ts = item.get("timestamp", "").replace("T", " ")[:16]
                ts_lbl = QLabel(f"⏱ {ts}")
                ts_lbl.setFont(QFont("Courier New", 7))
                ts_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
                b_lay.addWidget(ts_lbl)

                u_lbl = QLabel(f"You: {item.get('user', '')}")
                u_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
                u_lbl.setStyleSheet(f"color: {C.WHITE}; background: transparent;")
                u_lbl.setWordWrap(True)
                b_lay.addWidget(u_lbl)

                j_lbl = QLabel(f"JARVIS: {item.get('jarvis', '')}")
                j_lbl.setFont(QFont("Courier New", 8))
                j_lbl.setStyleSheet(f"color: {C.PRI}; background: transparent;")
                j_lbl.setWordWrap(True)
                b_lay.addWidget(j_lbl)

                self._list_lay.addWidget(box)

        except Exception as e:
            lbl = QLabel(f"Error loading history: {e}")
            lbl.setFont(QFont("Courier New", 8))
            lbl.setStyleSheet(f"color: {C.RED}; background: transparent;")
            self._list_lay.addWidget(lbl)

    def _do_search(self, text: str):
        self._load_entries(text.strip())


class PrivacyVeilOverlay(QWidget):
    """
    Futuristic cyber-security privacy veil overlay for J.A.R.V.I.S.
    Blurs and masks the underlying desktop interface when an onlooker
    is detected looking over the user's shoulder.
    """
    dismissed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("""
            PrivacyVeilOverlay {
                background: rgba(4, 11, 20, 246);
            }
        """)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(40, 40, 40, 40)

        card = QFrame()
        card.setFixedSize(540, 320)
        card.setStyleSheet(f"""
            QFrame {{
                background: #061220;
                border: 2px solid {C.RED};
                border-radius: 12px;
            }}
        """)
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(30, 24, 30, 24)
        c_lay.setSpacing(12)
        c_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        badge = QLabel("🛡️  SENTRY PRIVACY VEIL ENGAGED")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        badge.setStyleSheet(f"color: {C.RED}; background: transparent; border: none;")
        c_lay.addWidget(badge)

        warn_lbl = QLabel("⚠️  UNRECOGNIZED PRESENCE DETECTED BEHIND WORKSTATION")
        warn_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        warn_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        warn_lbl.setStyleSheet(f"color: {C.ACC2}; background: transparent; border: none;")
        c_lay.addWidget(warn_lbl)

        desc_lbl = QLabel(
            "Anti-Shoulder Surfer has blurred your sensitive dashboard widgets, "
            "academic documents, and conversation history to protect your privacy from onlookers."
        )
        desc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_lbl.setWordWrap(True)
        desc_lbl.setFont(QFont("Segoe UI", 8))
        desc_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; border: none;")
        c_lay.addWidget(desc_lbl)

        status_lbl = QLabel("👁️ Perimeter vision sentry active • Auto-restores when onlooker leaves")
        status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_lbl.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        status_lbl.setStyleSheet(f"color: {C.PRI}; background: transparent; border: none;")
        c_lay.addWidget(status_lbl)

        c_lay.addSpacing(6)

        btn_dismiss = QPushButton("DISMISS VEIL  [ESC]")
        btn_dismiss.setFixedHeight(34)
        btn_dismiss.setFixedWidth(200)
        btn_dismiss.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        btn_dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_dismiss.setStyleSheet(f"""
            QPushButton {{
                background: #140409;
                color: {C.RED};
                border: 1px solid {C.RED};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background: {C.RED};
                color: #ffffff;
            }}
        """)
        btn_dismiss.clicked.connect(self.dismissed.emit)
        c_lay.addWidget(btn_dismiss, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(card)

    def mousePressEvent(self, event):
        self.dismissed.emit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Space, Qt.Key.Key_Return):
            self.dismissed.emit()
        else:
            super().keyPressEvent(event)


class MainWindow(QMainWindow):
    _log_sig   = pyqtSignal(str)
    _state_sig = pyqtSignal(str)
    _notif_sig = pyqtSignal(str, str)
    _cam_frame_sig = pyqtSignal(object)
    _model_sig = pyqtSignal(str)
    _emotion_sig = pyqtSignal(str, str)
    _gesture_sig = pyqtSignal(str)
    _fps_throttle_sig = pyqtSignal(int)
    _privacy_veil_sig = pyqtSignal(bool, str)

    def __init__(self, face_path: str):
        super().__init__()
        self.setWindowTitle("J.A.R.V.I.S — MARK 58 (APEX CORE)")
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width()  - _DEFAULT_W) // 2,
            (screen.height() - _DEFAULT_H) // 2,
        )

        self.on_text_command  = None
        self.on_model_switch  = None
        self._muted           = False
        self._current_file: str | None = None

        central = QWidget()
        central.setStyleSheet(f"background: {C.BG};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._left_panel = self._build_left_panel()
        body.addWidget(self._left_panel, stretch=0)

        self.hud = HudCanvas(face_path)
        self.hud.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        body.addWidget(self.hud, stretch=5)

        self._right_panel = self._build_right_panel()
        body.addWidget(self._right_panel, stretch=0)

        root.addLayout(body, stretch=1)
        root.addWidget(self._build_footer())

        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)
        self._tick_clock()

        # Metrik güncelleme timer'ı
        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(2000)
        self._update_metrics()

        self._log_sig.connect(self._log.append_log)
        self._state_sig.connect(self._apply_state)
        self._notif_sig.connect(self._add_notification)
        self._cam_frame_sig.connect(self._cam_widget.update_frame)
        self._emotion_sig.connect(self._apply_emotion)
        self._gesture_sig.connect(self.hud.trigger_gesture)
        self._fps_throttle_sig.connect(self.hud.set_fps)

        self._overlay: SetupOverlay | None = None
        self._settings_overlay: SettingsOverlay | None = None
        self._history_overlay: HistoryOverlay | None = None
        self._privacy_veil: PrivacyVeilOverlay | None = None
        self._blur_effect: QGraphicsBlurEffect | None = None
        self._privacy_veil_sig.connect(self._on_set_privacy_veil)

        self._ready = self._check_config()
        self.ready_event = threading.Event()
        if self._ready:
            self.ready_event.set()
        else:
            self._show_setup()

        sc_mute = QShortcut(QKeySequence("F4"), self)
        sc_mute.activated.connect(self._toggle_mute)
        sc_full = QShortcut(QKeySequence("F11"), self)
        sc_full.activated.connect(self._toggle_fullscreen)
        sc_cam = QShortcut(QKeySequence("F6"), self)
        sc_cam.activated.connect(self._toggle_camera)
        sc_veil = QShortcut(QKeySequence("Escape"), self)
        sc_veil.activated.connect(self._dismiss_privacy_veil)

    def write_log(self, text: str):
        self._log_sig.emit(text)

    def _on_model_click(self, model_key: str):
        for k, btn in getattr(self, "_btn_models", {}).items():
            if k == model_key:
                btn.setStyleSheet(f"background: #002233; color: {C.PRI}; border: 1px solid {C.PRI}; border-radius: 3px;")
            else:
                btn.setStyleSheet(f"background: transparent; color: {C.TEXT_MED}; border: 1px solid {C.BORDER}; border-radius: 3px;")
        
        self.write_log(f"UI: 🧠 Switched AI Brain Model to '{model_key}'.")
        if callable(self.on_model_switch):
            try:
                self.on_model_switch(model_key)
            except Exception as e:
                self.write_log(f"ERR: Model switch callback failed: {e}")

    def _send_text_cmd(self, text: str):
        self.write_log(f"You: {text}")
        if callable(self.on_text_command):
            try:
                self.on_text_command(text)
            except Exception as e:
                self.write_log(f"ERR: Text command dispatch failed: {e}")

    def _toggle_camera(self):
        try:
            from actions.camera_system import camera_mgr
            res = camera_mgr.toggle_camera(player=self)
            if camera_mgr.is_active:
                camera_mgr.add_subscriber(lambda frame: self._cam_frame_sig.emit(frame))
                self._cam_btn.setText("📷  CAMERA ACTIVE  [F6]")
                self._cam_btn.setStyleSheet(f"background: #00140a; color: {C.GREEN}; border: 1px solid {C.GREEN}; border-radius: 3px;")
            else:
                self._cam_btn.setText("📷  CAMERA OFFLINE  [F6]")
                self._cam_btn.setStyleSheet(f"background: transparent; color: {C.TEXT_MED}; border: 1px solid {C.BORDER}; border-radius: 3px;")
                self._cam_widget.set_offline()
        except Exception as e:
            self.write_log(f"ERR: Camera toggle failed — {e}")

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def set_privacy_veil(self, enabled: bool, reason: str = ""):
        """Thread-safe trigger for Anti-Shoulder Surfer privacy veil."""
        self._privacy_veil_sig.emit(enabled, reason)

    def _dismiss_privacy_veil(self):
        """Disengages privacy veil and alerts sentry engine."""
        self._on_set_privacy_veil(False)
        try:
            from actions.anti_shoulder_surfer import get_anti_shoulder_surfer
            get_anti_shoulder_surfer().dismiss_veil()
        except Exception:
            pass

    def _on_set_privacy_veil(self, enabled: bool, reason: str = ""):
        """Engages or disengages privacy veil overlay and blur effects."""
        if enabled:
            if not self._privacy_veil:
                self._privacy_veil = PrivacyVeilOverlay(self)
                self._privacy_veil.dismissed.connect(self._dismiss_privacy_veil)
            self._privacy_veil.setGeometry(0, 0, self.width(), self.height())
            self._privacy_veil.show()
            self._privacy_veil.raise_()

            if self.centralWidget():
                self._blur_effect = QGraphicsBlurEffect(self)
                self._blur_effect.setBlurRadius(22.0)
                self.centralWidget().setGraphicsEffect(self._blur_effect)

            self.write_log("PRIVACY: 🛡️ Sentry Privacy Veil engaged — shoulder surfer detected.")
            self.push_notification("Sentry Privacy Veil active — screen obscured", "warning")
        else:
            if self._privacy_veil and self._privacy_veil.isVisible():
                self._privacy_veil.hide()
            if self.centralWidget():
                self.centralWidget().setGraphicsEffect(None)
            self.write_log("PRIVACY: Perimeter clear — Sentry Privacy Veil lifted.")
            self.push_notification("Perimeter clear — Workspace restored", "info")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cw = self.centralWidget()
        if cw:
            if self._overlay and self._overlay.isVisible():
                ow, oh = 460, 430
                self._overlay.setGeometry((cw.width() - ow) // 2, (cw.height() - oh) // 2, ow, oh)
            if self._settings_overlay and self._settings_overlay.isVisible():
                ow, oh = 420, 520
                self._settings_overlay.setGeometry((cw.width() - ow) // 2, (cw.height() - oh) // 2, ow, oh)
            if self._history_overlay and self._history_overlay.isVisible():
                ow, oh = 480, 520
                self._history_overlay.setGeometry((cw.width() - ow) // 2, (cw.height() - oh) // 2, ow, oh)
            if hasattr(self, "_privacy_veil") and self._privacy_veil and self._privacy_veil.isVisible():
                self._privacy_veil.setGeometry(0, 0, self.width(), self.height())

    def closeEvent(self, event):
        try:
            if hasattr(self, "_clock_tmr"):
                self._clock_tmr.stop()
            if hasattr(self, "_metric_tmr"):
                self._metric_tmr.stop()
            if hasattr(self, "hud") and hasattr(self.hud, "_tmr"):
                self.hud._tmr.stop()
            _metrics.stop()
            from actions.camera_system import camera_mgr
            if camera_mgr.is_active:
                camera_mgr.stop()
            from actions.anti_shoulder_surfer import get_anti_shoulder_surfer
            if get_anti_shoulder_surfer().is_active():
                get_anti_shoulder_surfer().stop_sentry()
        except Exception:
            pass
        super().closeEvent(event)

    def _update_metrics(self):
        snap = _metrics.snapshot()

        # CPU
        cpu = snap["cpu"]
        self._bar_cpu.set_value(cpu, f"{cpu:.0f}%")

        # MEM
        mem = snap["mem"]
        self._bar_mem.set_value(mem, f"{mem:.0f}%")

        # NET
        net = snap["net"]
        if net < 1.0:
            net_str = f"{net*1024:.0f}KB/s"
        else:
            net_str = f"{net:.1f}MB/s"
        net_pct = min(100, net * 10)  # 10 MB/s = %100
        self._bar_net.set_value(net_pct, net_str)

        # GPU
        gpu = snap["gpu"]
        if gpu >= 0:
            self._bar_gpu.set_value(gpu, f"{gpu:.0f}%")
        else:
            self._bar_gpu.set_value(0, "N/A")

        # TMP
        tmp = snap["tmp"]
        if tmp >= 0:
            tmp_pct = min(100, (tmp / 100) * 100)
            self._bar_tmp.set_value(tmp_pct, f"{tmp:.0f}°C")
        else:
            self._bar_tmp.set_value(0, "N/A")

        try:
            boot_t  = psutil.boot_time()
            elapsed = time.time() - boot_t
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            self._uptime_lbl.setText(f"UP  {h:02d}:{m:02d}")
        except Exception:
            self._uptime_lbl.setText("UP  --:--")

        try:
            proc_count = len(psutil.pids())
            self._proc_lbl.setText(f"PROC  {proc_count}")
        except Exception:
            self._proc_lbl.setText("PROC  --")


    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(54)
        w.setStyleSheet(f"background: {C.DARK}; border-bottom: 1px solid {C.BORDER_B};")
        self._header_widget = w
        lay = QHBoxLayout(w)
        lay.setContentsMargins(16, 0, 16, 0)

        def _badge(txt, color=C.TEXT_MED):
            l = QLabel(txt)
            l.setFont(QFont("Courier New", 8))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        lay.addWidget(_badge("MARK 58 // APEX CORE", C.PRI))
        lay.addStretch()

        mid = QVBoxLayout(); mid.setSpacing(1)
        title = QLabel("J.A.R.V.I.S")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Courier New", 17, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        mid.addWidget(title)
        sub = QLabel("Just A Rather Very Intelligent System")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setFont(QFont("Courier New", 7))
        sub.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        mid.addWidget(sub)
        lay.addLayout(mid)
        lay.addStretch()

        right_col = QVBoxLayout(); right_col.setSpacing(2)
        self._clock_lbl = QLabel("00:00:00")
        self._clock_lbl.setFont(QFont("Courier New", 14, QFont.Weight.Bold))
        self._clock_lbl.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        self._clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._clock_lbl)
        self._date_lbl = QLabel("")
        self._date_lbl.setFont(QFont("Courier New", 7))
        self._date_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._date_lbl)
        lay.addLayout(right_col)
        return w

    def _tick_clock(self):
        self._clock_lbl.setText(time.strftime("%H:%M:%S"))
        self._date_lbl.setText(time.strftime("%a %d %b %Y"))

    def _build_left_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_LEFT_W)
        w.setStyleSheet(f"background: {C.DARK}; border-right: 1px solid {C.BORDER};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 10, 8, 10)
        lay.setSpacing(6)

        hdr = QLabel("◈ SYS MONITOR")
        hdr.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent; "
                          f"border-bottom: 1px solid {C.BORDER}; padding-bottom: 4px;")
        lay.addWidget(hdr)
        lay.addSpacing(2)

        self._bar_cpu = MetricBar("CPU", C.PRI)
        self._bar_mem = MetricBar("MEM", C.ACC2)
        self._bar_net = MetricBar("NET", C.GREEN)
        self._bar_gpu = MetricBar("GPU", C.ACC)
        self._bar_tmp = MetricBar("TMP", "#ff6688")

        for bar in [self._bar_cpu, self._bar_mem, self._bar_net,
                    self._bar_gpu, self._bar_tmp]:
            lay.addWidget(bar)

        lay.addSpacing(4)

        info_panel = QWidget()
        info_panel.setStyleSheet(
            f"background: {C.PANEL2}; border: 1px solid {C.BORDER}; border-radius: 4px;"
        )
        ip_lay = QVBoxLayout(info_panel)
        ip_lay.setContentsMargins(6, 5, 6, 5)
        ip_lay.setSpacing(3)

        self._uptime_lbl = QLabel("UP  --:--")
        self._uptime_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._uptime_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent; border: none;")
        ip_lay.addWidget(self._uptime_lbl)

        self._proc_lbl = QLabel("PROC  --")
        self._proc_lbl.setFont(QFont("Courier New", 8))
        self._proc_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; border: none;")
        ip_lay.addWidget(self._proc_lbl)

        os_name = {"Windows": "WIN", "Darwin": "macOS", "Linux": "LINUX"}.get(_OS, _OS.upper())
        os_lbl = QLabel(f"OS  {os_name}")
        os_lbl.setFont(QFont("Courier New", 8))
        os_lbl.setStyleSheet(f"color: {C.ACC2}; background: transparent; border: none;")
        ip_lay.addWidget(os_lbl)

        lay.addWidget(info_panel)
        lay.addSpacing(4)

        # Tactical Quick Action Bar
        t_hdr = QLabel("◈ QUICK PROTOCOLS")
        t_hdr.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        t_hdr.setStyleSheet(f"color: {C.PRI}; background: transparent; border-bottom: 1px solid {C.BORDER}; padding-bottom: 2px;")
        lay.addWidget(t_hdr)

        btn_grid = QVBoxLayout()
        btn_grid.setSpacing(3)

        tactical_cmds = [
            ("🛡️ SENTRY",    "sentry mode"),
            ("👻 GHOST",     "ghost protocol"),
            ("🛠️ AUTOPILOT", "setup new project"),
            ("☀️ BRIEFING",  "daily briefing")
        ]

        for label, cmd_text in tactical_cmds:
            btn = QPushButton(label)
            btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            btn.setFixedHeight(22)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {C.PANEL2}; color: {C.TEXT_MED};
                    border: 1px solid {C.BORDER_A}; border-radius: 3px;
                }}
                QPushButton:hover {{
                    color: {C.PRI}; border: 1.5px solid {C.PRI}; background: #06283d;
                }}
            """)
            btn.clicked.connect(lambda _, t=cmd_text: self._send_text_cmd(t))
            btn_grid.addWidget(btn)

        lay.addLayout(btn_grid)
        lay.addSpacing(4)

        # Dashboard Widgets
        dash_panel = QWidget()
        dash_panel.setStyleSheet(f"background: {C.PANEL2}; border: 1px solid {C.BORDER}; border-radius: 4px;")
        dp_lay = QVBoxLayout(dash_panel)
        dp_lay.setContentsMargins(6, 5, 6, 5)
        dp_lay.setSpacing(3)

        d_hdr = QLabel("◈ DASHBOARD")
        d_hdr.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        d_hdr.setStyleSheet(f"color: {C.PRI}; background: transparent; border: none;")
        dp_lay.addWidget(d_hdr)

        self._dash_wx = QLabel("🌤  WX  --")
        self._dash_wx.setFont(QFont("Courier New", 7))
        self._dash_wx.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; border: none;")
        dp_lay.addWidget(self._dash_wx)

        self._dash_evt = QLabel("📅  EVT --")
        self._dash_evt.setFont(QFont("Courier New", 7))
        self._dash_evt.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; border: none;")
        dp_lay.addWidget(self._dash_evt)

        self._dash_mail = QLabel("✉  MAIL --")
        self._dash_mail.setFont(QFont("Courier New", 7))
        self._dash_mail.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; border: none;")
        dp_lay.addWidget(self._dash_mail)

        lay.addWidget(dash_panel)
        lay.addSpacing(4)

        # Notification Center
        n_hdr = QLabel("🔔 NOTIFICATIONS")
        n_hdr.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        n_hdr.setStyleSheet(f"color: {C.ACC2}; background: transparent; border-bottom: 1px solid {C.BORDER}; padding-bottom: 2px;")
        lay.addWidget(n_hdr)

        self._notif_scroll = QScrollArea()
        self._notif_scroll.setWidgetResizable(True)
        self._notif_scroll.setFixedHeight(90)
        self._notif_scroll.setStyleSheet(f"""
            QScrollArea {{ background: {C.PANEL2}; border: 1px solid {C.BORDER}; border-radius: 3px; }}
            QScrollBar:vertical {{ background: {C.BG}; width: 4px; border: none; }}
            QScrollBar::handle:vertical {{ background: {C.BORDER_B}; border-radius: 2px; }}
        """)
        self._notif_inner = QWidget()
        self._notif_inner.setStyleSheet("background: transparent;")
        self._notif_lay = QVBoxLayout(self._notif_inner)
        self._notif_lay.setContentsMargins(4, 3, 4, 3)
        self._notif_lay.setSpacing(3)
        self._notif_scroll.setWidget(self._notif_inner)
        lay.addWidget(self._notif_scroll)

        lay.addStretch()

        for txt, col in [
            ("AI CORE\nACTIVE",     C.GREEN),
            ("SEC\nCLEARED",        C.PRI),
            ("PROTOCOL\nMARK 58",   C.TEXT_DIM),
        ]:
            lbl = QLabel(txt)
            lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                f"color: {col}; background: {C.PANEL2};"
                f"border: 1px solid {C.BORDER_A}; border-radius: 3px; padding: 4px;"
            )
            lay.addWidget(lbl)

        return w
    def _build_right_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_RIGHT_W)
        w.setStyleSheet(f"background: {C.DARK}; border-left: 1px solid {C.BORDER};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        def _sec(txt):
            l = QLabel(f"▸ {txt}")
            l.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            l.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            return l

        lay.addWidget(_sec("BRAIN ENGINE SELECTOR"))

        # Model Selector Bar
        model_panel = QWidget()
        model_panel.setStyleSheet(f"background: {C.PANEL2}; border: 1px solid {C.BORDER}; border-radius: 4px; padding: 2px;")
        mp_lay = QHBoxLayout(model_panel)
        mp_lay.setContentsMargins(4, 4, 4, 4)
        mp_lay.setSpacing(4)

        self._btn_models = {}
        models_info = [
            ("2.5 Flash", "gemini-2.5-flash-native-audio-latest"),
            ("2.5 Pro",   "gemini-2.5-pro"),
            ("2.0 Lite",  "gemini-2.0-flash-lite"),
            ("Omni",      "omniroute")
        ]

        for label, m_key in models_info:
            btn = QPushButton(label)
            btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            btn.setFixedHeight(22)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            
            # Default active state for 2.5 Flash
            if m_key == "gemini-2.5-flash-native-audio-latest":
                btn.setStyleSheet(f"background: #002233; color: {C.PRI}; border: 1px solid {C.PRI}; border-radius: 3px;")
            else:
                btn.setStyleSheet(f"background: transparent; color: {C.TEXT_MED}; border: 1px solid {C.BORDER}; border-radius: 3px;")
            
            btn.clicked.connect(lambda _, k=m_key: self._on_model_click(k))
            mp_lay.addWidget(btn)
            self._btn_models[m_key] = btn

        lay.addWidget(model_panel)
        lay.addSpacing(2)

        lay.addWidget(_sec("ACTIVITY LOG"))
        self._log = LogWidget()
        lay.addWidget(self._log, stretch=1)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        # Spotify AI DJ Media Glass Card
        lay.addWidget(_sec("SPOTIFY AI DJ CONTROLLER"))
        spot_card = QWidget()
        spot_card.setStyleSheet(f"background: {C.PANEL2}; border: 1.5px solid {C.BORDER_B}; border-radius: 6px; padding: 4px;")
        sp_lay = QHBoxLayout(spot_card)
        sp_lay.setContentsMargins(6, 4, 6, 4)
        sp_lay.setSpacing(6)

        sp_info = QVBoxLayout()
        sp_info.setSpacing(1)
        sp_title = QLabel("🎵  JARVIS Audio Engine")
        sp_title.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        sp_title.setStyleSheet(f"color: {C.GREEN}; background: transparent;")
        sp_sub = QLabel("Spotify AI DJ Ready")
        sp_sub.setFont(QFont("Courier New", 6))
        sp_sub.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        sp_info.addWidget(sp_title)
        sp_info.addWidget(sp_sub)
        sp_lay.addLayout(sp_info, stretch=1)

        sp_btn_play = QPushButton("▶")
        sp_btn_next = QPushButton("⏭")
        for b in [sp_btn_play, sp_btn_next]:
            b.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            b.setFixedSize(24, 22)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f"QPushButton {{ background: {C.PANEL}; color: {C.PRI}; border: 1px solid {C.BORDER_A}; border-radius: 3px; }} QPushButton:hover {{ color: {C.GREEN}; border: 1px solid {C.GREEN}; }}")
        
        sp_btn_play.clicked.connect(lambda: self._send_text_cmd("play spotify"))
        sp_btn_next.clicked.connect(lambda: self._send_text_cmd("next song on spotify"))
        
        sp_lay.addWidget(sp_btn_play)
        sp_lay.addWidget(sp_btn_next)
        lay.addWidget(spot_card)
        lay.addSpacing(2)

        lay.addWidget(_sec("FILE UPLOAD"))
        self._drop_zone = FileDropZone()
        self._drop_zone.file_selected.connect(self._on_file_selected)
        lay.addWidget(self._drop_zone)

        self._file_hint = QLabel("No file loaded — drop or click above to upload")
        self._file_hint.setFont(QFont("Courier New", 7))
        self._file_hint.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._file_hint.setWordWrap(True)
        lay.addWidget(self._file_hint)

        lay.addWidget(_sec("CAMERA FEED"))
        self._cam_widget = CameraPreviewWidget()
        lay.addWidget(self._cam_widget)

        self._cam_btn = QPushButton("📷  CAMERA OFFLINE  [F6]")
        self._cam_btn.setFixedHeight(26)
        self._cam_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._cam_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cam_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{
                color: {C.PRI}; border: 1px solid {C.BORDER_B};
            }}
        """)
        self._cam_btn.clicked.connect(self._toggle_camera)
        lay.addWidget(self._cam_btn)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep2)

        lay.addWidget(_sec("COMMAND INPUT"))
        lay.addLayout(self._build_input_row())

        self._mute_btn = QPushButton("🎙  MICROPHONE ACTIVE")
        self._mute_btn.setFixedHeight(30)
        self._mute_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._toggle_mute)
        self._style_mute_btn()
        lay.addWidget(self._mute_btn)

        fs_btn = QPushButton("⛶  FULLSCREEN  [F11]")
        fs_btn.setFixedHeight(26)
        fs_btn.setFont(QFont("Courier New", 7))
        fs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        fs_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{
                color: {C.PRI}; border: 1px solid {C.BORDER_B};
            }}
        """)
        fs_btn.clicked.connect(self._toggle_fullscreen)
        lay.addWidget(fs_btn)

        hist_btn = QPushButton("📜  HISTORY")
        hist_btn.setFixedHeight(26)
        hist_btn.setFont(QFont("Courier New", 7))
        hist_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        hist_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{
                color: {C.WHITE}; border: 1px solid {C.PRI};
            }}
        """)
        hist_btn.clicked.connect(self._toggle_history)
        lay.addWidget(hist_btn)

        settings_btn = QPushButton("⚙  SETTINGS")
        settings_btn.setFixedHeight(26)
        settings_btn.setFont(QFont("Courier New", 7))
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.ACC2};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{
                color: {C.PRI}; border: 1px solid {C.ACC2};
            }}
        """)
        settings_btn.clicked.connect(self._toggle_settings)
        lay.addWidget(settings_btn)

        return w

    def _build_input_row(self) -> QHBoxLayout:
        row = QHBoxLayout(); row.setSpacing(5)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command or question…")
        self._input.setFont(QFont("Courier New", 9))
        self._input.setFixedHeight(30)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d14; color: {C.WHITE};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 3px 7px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        self._input.returnPressed.connect(self._send)
        row.addWidget(self._input)

        send = QPushButton("▸")
        send.setFixedSize(30, 30)
        send.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        send.clicked.connect(self._send)
        row.addWidget(send)
        return row

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(22)
        w.setStyleSheet(f"background: {C.DARK}; border-top: 1px solid {C.BORDER};")
        self._footer_widget = w
        lay = QHBoxLayout(w); lay.setContentsMargins(14, 0, 14, 0)

        def _fl(txt, color=C.TEXT_MED):
            l = QLabel(txt); l.setFont(QFont("Courier New", 7))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        lay.addWidget(_fl("[F4] Mute  ·  [F6] Camera  ·  [F11] Fullscreen"))
        lay.addStretch()
        lay.addWidget(_fl("Akul Bhatnagar Industries  ·  MARK 58  ·  CLASSIFIED"))
        lay.addStretch()
        lay.addWidget(_fl("© STARK INDUSTRIES", C.PRI_DIM))
        return w

    def _on_file_selected(self, path: str):
        self._current_file = path
        p    = Path(path)
        cat  = _file_category(p)
        icon, _ = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size = _fmt_size(p.stat().st_size)
        self._file_hint.setText(f"{icon}  {p.name}  ·  {size}  ·  Tell JARVIS what to do with it")
        self._log.append_log(f"FILE: {p.name} ({size}) loaded")
        if self.on_text_command:
            msg = (
                f"[FILE_UPLOADED] path={path} | name={p.name} | "
                f"type={p.suffix.lstrip('.')} | size={size} | "
                f"Briefly tell the user you can see the file '{p.name}' "
                f"({size}) has been uploaded and ask what they'd like to do with it."
            )
            threading.Thread(target=self.on_text_command, args=(msg,), daemon=True).start()

    def _toggle_mute(self):
        self._muted = not self._muted
        self.hud.muted = self._muted
        self._style_mute_btn()
        if self._muted:
            self._apply_state("MUTED")
            self._log.append_log("SYS: Microphone muted.")
        else:
            self._apply_state("LISTENING")
            self._log.append_log("SYS: Microphone active.")

    def _style_mute_btn(self):
        if self._muted:
            self._mute_btn.setText("🔇  MICROPHONE MUTED")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #140006; color: {C.MUTED_C};
                    border: 1px solid {C.MUTED_C}; border-radius: 3px;
                }}
            """)
        else:
            self._mute_btn.setText("🎙  MICROPHONE ACTIVE")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #00140a; color: {C.GREEN};
                    border: 1px solid {C.GREEN}; border-radius: 3px;
                }}
                QPushButton:hover {{ background: #001f10; }}
            """)

    def _send(self):
        txt = self._input.text().strip()
        if not txt: return
        self._input.clear()
        self._log.append_log(f"You: {txt}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,), daemon=True).start()

    def _apply_state(self, state: str):
        self.hud.state    = state
        self.hud.speaking = (state == "SPEAKING")

    def _apply_emotion(self, state: str, color_hex: str):
        self.hud.set_emotion(state, color_hex)

    def set_emotion(self, state: str, color_hex: str = ""):
        self._emotion_sig.emit(state, color_hex)

    def trigger_gesture(self, gesture: str):
        self._gesture_sig.emit(gesture)

    def set_hud_fps(self, fps: int):
        self._fps_throttle_sig.emit(fps)

    def _check_config(self) -> bool:
        if not API_FILE.exists(): return False
        try:
            d = json.loads(API_FILE.read_text(encoding="utf-8"))
            return (bool(d.get("gemini_api_key")) and
                    bool(d.get("openrouter_api_key")) and
                    bool(d.get("os_system")))
        except Exception:
            return False

    def _toggle_settings(self):
        if self._settings_overlay and self._settings_overlay.isVisible():
            self._settings_overlay.hide()
            return
        ov = SettingsOverlay(self.centralWidget())
        cw = self.centralWidget()
        ow, oh = 420, 520
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.settings_changed.connect(
            lambda d: self._log.append_log("SYS: Settings updated.")
        )
        ov.show()
        self._settings_overlay = ov

    def _show_setup(self):
        ov = SetupOverlay(self.centralWidget())
        cw = self.centralWidget()
        ow, oh = 460, 430
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.done.connect(self._on_setup_done)
        ov.show()
        self._overlay = ov

    # Change signature:
    def _on_setup_done(self, key: str, or_key: str, os_name: str):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        API_FILE.write_text(
            json.dumps({
                "gemini_api_key":    key,
                "openrouter_api_key": or_key,
                "os_system":         os_name,
            }, indent=4),
            encoding="utf-8",
        )
        self._ready = True
        self.ready_event.set()
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        self._apply_state("LISTENING")
        self._log.append_log(f"SYS: Initialised. OS={os_name.upper()}. JARVIS online.")

    def _toggle_history(self):
        if self._history_overlay and self._history_overlay.isVisible():
            self._history_overlay.hide()
            return
        ov = HistoryOverlay(self.centralWidget())
        cw = self.centralWidget()
        ow, oh = 480, 520
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.show()
        self._history_overlay = ov

    def push_notification(self, msg: str, level: str = "info"):
        self._notif_sig.emit(msg, level)

    def _add_notification(self, msg: str, level: str):
        colors = {"info": C.PRI, "warning": C.ACC2, "alert": C.RED, "success": C.GREEN}
        col = colors.get(level, C.TEXT_MED)
        lbl = QLabel(f"• {msg}")
        lbl.setFont(QFont("Courier New", 7))
        lbl.setStyleSheet(f"color: {col}; background: transparent;")
        lbl.setWordWrap(True)
        self._notif_lay.insertWidget(0, lbl)

    def update_dashboard(self, wx: str = None, evt: str = None, mail: str = None):
        if wx is not None:
            self._dash_wx.setText(f"🌤  {wx}")
        if evt is not None:
            self._dash_evt.setText(f"📅  {evt}")
    def set_war_theme(self, enabled: bool):
        if enabled:
            C.BG        = "#1a0205"
            C.PANEL     = "#0d0103"
            C.PANEL2    = "#140205"
            C.BORDER    = "#660011"
            C.BORDER_B  = "#99001a"
            C.BORDER_A  = "#cc0022"
            C.PRI       = "#ff1a3c"
            C.PRI_DIM   = "#990d20"
            C.PRI_GHO   = "#330008"
            C.ACC       = "#ffb700"
            C.ACC2      = "#ffea00"
            C.TEXT      = "#ffb8c6"
            C.TEXT_DIM  = "#882b3d"
            C.TEXT_MED  = "#cc445d"
            C.DARK      = "#0d0103"
            C.BAR_BG    = "#140205"
            self._log.append_log("SYS: WAR PROTOCOL ENGAGED. TACTICAL CRIMSON HUD ACTIVE.")
            self.push_notification("WAR PROTOCOL ENGAGED -- MAXIMUM PERFORMANCE", "alert")
        else:
            C.BG        = "#00060a"
            C.PANEL     = "#010d14"
            C.PANEL2    = "#010f18"
            C.BORDER    = "#0d3347"
            C.BORDER_B  = "#1a5c7a"
            C.BORDER_A  = "#0f4060"
            C.PRI       = "#00d4ff"
            C.PRI_DIM   = "#007a99"
            C.PRI_GHO   = "#001f2e"
            C.ACC       = "#ff6b00"
            C.ACC2      = "#ffcc00"
            C.TEXT      = "#8ffcff"
            C.TEXT_DIM  = "#3a8a9a"
            C.TEXT_MED  = "#5ab8cc"
            C.DARK      = "#000d14"
            C.BAR_BG    = "#011520"
            self._log.append_log("SYS: WAR PROTOCOL DEACTIVATED. STANDBY HUD RESTORED.")
            self.push_notification("War protocol deactivated -- Standby mode", "info")

        # Dynamically refresh stylesheets of all outer structural containers
        try:
            if hasattr(self, "_header_widget") and self._header_widget:
                self._header_widget.setStyleSheet(f"background: {C.DARK}; border-bottom: 1px solid {C.BORDER_B};")
            if hasattr(self, "_footer_widget") and self._footer_widget:
                self._footer_widget.setStyleSheet(f"background: {C.DARK}; border-top: 1px solid {C.BORDER};")
            if hasattr(self, "_left_panel") and self._left_panel:
                self._left_panel.setStyleSheet(f"background: {C.DARK}; border-right: 1px solid {C.BORDER};")
            if hasattr(self, "_right_panel") and self._right_panel:
                self._right_panel.setStyleSheet(f"background: {C.DARK}; border-left: 1px solid {C.BORDER};")
            if self.centralWidget():
                self.centralWidget().setStyleSheet(f"background: {C.BG};")
            if hasattr(self, "hud") and self.hud:
                self.hud.update()
        except Exception:
            pass
        self.update()


class JarvisOpeningScreen(QWidget):
    """
    Sleek, low-energy Stark Industries boot splash for J.A.R.V.I.S. Mark 58.
    Features:
    - OLED-black canvas (#040914) saving power on OLED/LED displays.
    - Concentric rotating Arc Reactor glow with tech segments.
    - Battery-aware auto-tuning (Eco-Boot Mode: lower tick rate on battery).
    - Sequential subsystem initialization telemetry.
    - Auto-dismisses smoothly into MainWindow and tears down all timers.
    - Keyboard/mouse dismiss override (Space, Enter, Escape, or Click to skip).
    """
    def __init__(self, on_complete=None, parent=None):
        super().__init__(parent)
        self.on_complete = on_complete
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._w, self._h = 680, 420
        self.resize(self._w, self._h)

        # Center on primary screen
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width() - self._w) // 2,
            (screen.height() - self._h) // 2
        )

        # Power / Battery Telemetry Check
        self._on_battery = False
        self._battery_text = "⚡ AC POWER CONNECTED • PERFORMANCE PROFILE: OPTIMAL"
        try:
            bat = psutil.sensors_battery()
            if bat:
                self._on_battery = not bat.power_plugged
                plug_str = "PLUGGED IN" if bat.power_plugged else "ON BATTERY"
                eco_str = "ECO POWER ACTIVE" if self._on_battery else "OPTIMAL"
                self._battery_text = f"⚡ {bat.percent}% [{plug_str}] • ECO POWER PROFILE: {eco_str}"
        except Exception:
            pass

        # Energy-aware timing:
        # On battery: 20 FPS (50ms interval), 30 steps total (~1.5s total duration)
        # On AC: 28 FPS (35ms interval), 50 steps total (~1.75s total duration)
        self._step_interval = 50 if self._on_battery else 35
        self._max_steps = 30 if self._on_battery else 50
        self._current_step = 0
        self._angle = 0.0

        # Check codebase integrity seal
        seal_text = "[✔] SHA-256 INTEGRITY SEAL: UNCOMPROMISED"
        try:
            from core.server_security import IntegritySeal
            res = IntegritySeal.verify_integrity()
            if not res.get("is_valid", True):
                seal_text = "[!] CODE INTEGRITY WARNING: TAMPER DETECTED"
        except Exception:
            pass

        self._subsystems = [
            (0.12, "[✔] NEURAL ENGINE: GEMINI 2.0 / 3.8 FLASH READY"),
            (0.30, "[✔] STUNT DESKTOP PLATFORM MESH: CONNECTED"),
            (0.50, "[✔] 16:9 PRESENTATION STUDIO & EXECUTIVE DOCS: LOADED"),
            (0.70, "[✔] LOCALHOST THREAT SHIELD & SECURITY GOVERNOR: ACTIVE"),
            (0.85, seal_text),
        ]

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(self._step_interval)

    def _on_tick(self):
        self._current_step += 1
        self._angle = (self._angle + 4.5) % 360.0
        self.update()

        if self._current_step >= self._max_steps:
            self._timer.stop()
            self._finish()

    def _finish(self):
        if hasattr(self, "_timer") and self._timer.isActive():
            self._timer.stop()
        if self.on_complete:
            cb = self.on_complete
            self.on_complete = None
            cb()
        self.close()

    def mousePressEvent(self, event):
        self._finish()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape):
            self._finish()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. Base Dark Card
        card_rect = QRectF(10, 10, self._w - 20, self._h - 20)
        p.setPen(QPen(QColor(C.BORDER), 1.5))
        p.setBrush(QBrush(QColor("#040b14")))
        p.drawRoundedRect(card_rect, 16.0, 16.0)

        # Subtle Radial Glow behind Arc Reactor
        cx, cy = self._w / 2.0, 125.0
        glow = QRadialGradient(cx, cy, 110)
        glow.setColorAt(0.0, QColor(0, 240, 255, 38 if not self._on_battery else 20))
        glow.setColorAt(0.7, QColor(0, 136, 179, 12 if not self._on_battery else 6))
        glow.setColorAt(1.0, QColor(4, 11, 20, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(cx, cy), 110, 110)

        # 2. Concentric Arc Reactor Geometry
        p.save()
        p.translate(cx, cy)
        p.rotate(self._angle)

        # Outer Segmented Ring
        p.setPen(QPen(QColor(C.PRI), 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0, 0), 48, 48)

        # 8 Radial Notches
        p.setPen(QPen(QColor(C.PRI_DIM), 1.5))
        for i in range(8):
            rad = i * (math.pi / 4.0)
            x1, y1 = 40.0 * math.cos(rad), 40.0 * math.sin(rad)
            x2, y2 = 48.0 * math.cos(rad), 48.0 * math.sin(rad)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # Counter-rotating Inner Ring
        p.rotate(-self._angle * 2.2)
        p.setPen(QPen(QColor(C.BORDER_A), 1.2, Qt.PenStyle.DashLine))
        p.drawEllipse(QPointF(0, 0), 32, 32)
        p.restore()

        # Inner Glowing Core
        core_grad = QRadialGradient(cx, cy, 20)
        core_grad.setColorAt(0.0, QColor("#ffffff"))
        core_grad.setColorAt(0.5, QColor(C.PRI))
        core_grad.setColorAt(1.0, QColor(C.PRI_GHO))
        p.setPen(QPen(QColor(C.PRI), 1.0))
        p.setBrush(QBrush(core_grad))
        p.drawEllipse(QPointF(cx, cy), 16, 16)

        # 3. Branding Typography
        p.setPen(QColor(C.WHITE))
        font_title = QFont("Segoe UI", 18, QFont.Weight.Bold)
        p.setFont(font_title)
        p.drawText(QRectF(20, 195, self._w - 40, 32), Qt.AlignmentFlag.AlignCenter, "J.A.R.V.I.S.   •   MARK 58")

        font_sub = QFont("Segoe UI", 9, QFont.Weight.DemiBold)
        p.setFont(font_sub)
        p.setPen(QColor(C.PRI))
        p.drawText(QRectF(20, 226, self._w - 40, 20), Qt.AlignmentFlag.AlignCenter, "STARK INDUSTRIES AUTONOMOUS EXECUTIVE OS")

        # Battery / Eco-Status
        font_eco = QFont("Segoe UI", 8)
        p.setFont(font_eco)
        p.setPen(QColor(C.GREEN if not self._on_battery else C.ACC2))
        p.drawText(QRectF(20, 248, self._w - 40, 18), Qt.AlignmentFlag.AlignCenter, self._battery_text)

        # 4. Subsystems Boot Sequence Checklist (5 items)
        progress_ratio = min(1.0, self._current_step / float(self._max_steps))
        font_sys = QFont("Segoe UI", 8, QFont.Weight.Bold)
        p.setFont(font_sys)

        start_y = 268
        for thresh, label in self._subsystems:
            if progress_ratio >= thresh:
                color = C.RED if "TAMPER" in label or "WARNING" in label else C.TEXT_MED
                p.setPen(QColor(color))
                p.drawText(QRectF(80, start_y, self._w - 160, 16), Qt.AlignmentFlag.AlignLeft, label)
            else:
                p.setPen(QColor(C.TEXT_DIM))
                p.drawText(QRectF(80, start_y, self._w - 160, 16), Qt.AlignmentFlag.AlignLeft, f"[ ] {label[4:]}")
            start_y += 17

        # 5. Energy-Efficient Progress Bar
        bar_x, bar_y, bar_w, bar_h = 80, 362, self._w - 160, 6
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#0d2038")))
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 3, 3)

        fill_w = bar_w * progress_ratio
        if fill_w > 0:
            fill_grad = QLinearGradient(bar_x, bar_y, bar_x + fill_w, bar_y)
            fill_grad.setColorAt(0.0, QColor(C.PRI_DIM))
            fill_grad.setColorAt(1.0, QColor(C.PRI))
            p.setBrush(QBrush(fill_grad))
            p.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h), 3, 3)

        # 6. Skip Instruction Hint
        font_hint = QFont("Segoe UI", 7)
        p.setFont(font_hint)
        p.setPen(QColor(C.TEXT_DIM))
        p.drawText(QRectF(20, 378, self._w - 40, 16), Qt.AlignmentFlag.AlignCenter, "Press Space, Enter, or Click to Engage Console immediately")


class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app
    def mainloop(self):
        self._app.exec()
    def protocol(self, *_):
        pass


class JarvisUI:
    def __init__(self, face_path: str, size=None, show_splash: bool = True):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        self._win = MainWindow(face_path)
        self.root = _RootShim(self._app)

        if show_splash:
            self._splash = JarvisOpeningScreen(on_complete=self._win.show)
            self._splash.show()
        else:
            self._win.show()

    def set_war_theme(self, enabled: bool):
        self._win.set_war_theme(enabled)

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if v != self._win._muted:
            self._win._toggle_mute()

    @property
    def current_file(self) -> str | None:
        return self._win._drop_zone.current_file()

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def set_emotion(self, state: str, color_hex: str = ""):
        self._win._emotion_sig.emit(state, color_hex)

    def trigger_gesture(self, gesture: str):
        self._win.trigger_gesture(gesture)

    def set_hud_fps(self, fps: int):
        self._win.set_hud_fps(fps)

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    def push_notification(self, msg: str, level: str = "info"):
        self._win.push_notification(msg, level)

    def update_dashboard(self, wx: str = None, evt: str = None, mail: str = None):
        self._win.update_dashboard(wx, evt, mail)

    def wait_for_api_key(self):
        if hasattr(self._win, "ready_event"):
            self._win.ready_event.wait()
        else:
            while not self._win._ready:
                time.sleep(0.1)

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")

    def set_privacy_veil(self, enabled: bool, reason: str = ""):
        """Triggers or dismisses the Anti-Shoulder Surfer privacy veil."""
        self._win.set_privacy_veil(enabled, reason)

    def dismiss_privacy_veil(self):
        """Manually dismisses the privacy veil."""
        self._win._dismiss_privacy_veil()