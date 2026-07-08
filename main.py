#!/usr/bin/env python3
"""Simple automatic vertical Shorts/Reels video editor for Windows."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, scrolledtext, ttk

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk
from datetime import datetime, timezone

# Google OAuth and YouTube API imports
try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    HAS_GOOGLE_API = True
except ImportError:
    HAS_GOOGLE_API = False

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

APP_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = APP_DIR / "settings.json"
PRESETS_DIR = APP_DIR / "presets"
OUTPUT_DIR = APP_DIR / "output"

CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1920
PREVIEW_DISPLAY_W = 280
PREVIEW_DISPLAY_H = int(PREVIEW_DISPLAY_W * CANVAS_HEIGHT / CANVAS_WIDTH)
DEFAULT_FONT = r"C:\Windows\Fonts\arialbd.ttf"
DEFAULT_CLAP_SOUND = ""
SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".wmv"}

QUALITY_PRESETS = {
    "high": {"crf": "18", "preset": "slow", "label": "High quality (larger file)"},
    "balanced": {"crf": "23", "preset": "medium", "label": "Balanced (recommended)"},
    "small": {"crf": "28", "preset": "fast", "label": "Smaller file (lower quality)"},
}

TEXT_CASE_OPTIONS = {
    "none": "Normal",
    "uppercase": "UPPERCASE",
    "lowercase": "lowercase",
    "title": "Title Case",
    "sentence": "Sentence case",
}

THEME = {
    "bg": "#12141a",
    "surface": "#1a1e26",
    "surface2": "#242a35",
    "border": "#343b48",
    "text": "#eef0f4",
    "text_muted": "#8b939f",
    "accent": "#5b8def",
    "accent_hover": "#7aa3f5",
    "success": "#3dd68c",
    "preview_bg": "#0a0b0e",
    "video_outline": "#5b8def",
    "text_outline": "#3dd68c",
}


# ---------------------------------------------------------------------------
# Settings model
# ---------------------------------------------------------------------------


@dataclass
class TextOverlay:
    id: str
    label: str
    text: str = ""
    text_case: str = "none"
    text_spans: list = field(default_factory=list)
    first_line_color: str = "#FFD700"
    text_position: str = "top"
    text_custom_x: int = 0
    text_custom_y: int = 120
    font_size: int = 72
    first_line_font_size: int = 92
    font_color: str = "#FFFFFF"
    font_path: str = DEFAULT_FONT
    text_box_enabled: bool = False
    text_box_color: str = "#000000"
    text_box_opacity: float = 0.5
    text_shadow_enabled: bool = True
    text_outline_enabled: bool = True
    outline_color: str = "#000000"
    outline_size: int = 4


@dataclass
class EditorSettings:
    video_path: str = ""
    text: str = ""
    text_case: str = "none"
    text_spans: list = field(default_factory=list)
    first_line_color: str = "#FFFFFF"
    background_color: str = "#000000"
    video_position: str = "center"
    video_custom_x: int = 0
    video_custom_y: int = 0
    video_scale: float = 1.0
    video_center_align: bool = True
    crop_mode: bool = False
    text_position: str = "top"
    text_custom_x: int = 0
    text_custom_y: int = 120
    font_size: int = 72
    first_line_font_size: int = 92
    font_color: str = "#FFFFFF"
    font_path: str = DEFAULT_FONT
    text_box_enabled: bool = False
    text_box_color: str = "#000000"
    text_box_opacity: float = 0.5
    text_shadow_enabled: bool = True
    text_outline_enabled: bool = True
    outline_color: str = "#000000"
    outline_size: int = 4
    text_overlays: list = field(default_factory=list)
    active_text_overlay_id: str = "title"
    output_folder: str = ""
    output_filename: str = "shorts_output"
    export_quality: str = "balanced"
    end_sound_enabled: bool = False
    end_sound_path: str = DEFAULT_CLAP_SOUND
    end_sound_start_before_end: float = 5.0
    repeat_clip_twice: bool = False
    clip1_trim_start: float = 0.0
    clip1_trim_end: float = 0.0
    clip2_trim_start: float = 0.0
    clip2_trim_end: float = 0.0
    openai_api_key: str = ""
    openai_model: str = "gpt-5.5"
    metadata_system_prompt: str = (
        "You are a YouTube Shorts metadata expert. Return exactly four labeled sections: "
        "Video Text:, Title:, Description:, Tags:. Video Text must be exactly two lines: "
        "line 1 is the player's name, line 2 is a catchy 3-5 word phrase. Tags must be comma separated."
    )
    metadata_user_prompt: str = ""
    generated_video_text: str = ""
    generated_title: str = ""
    generated_description: str = ""
    generated_tags: str = ""
    last_preset: str = ""
    last_upload_time: str = ""
    upload_title: str = ""
    upload_description: str = ""
    upload_tags: str = ""
    upload_queue: bool = True
    last_upload_title: str = ""
    export_counts: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.output_folder:
            self.output_folder = str(OUTPUT_DIR)


def default_settings() -> EditorSettings:
    settings = EditorSettings()
    settings.text_overlays = [overlay_to_dict(o) for o in default_text_overlays()]
    return settings


def overlay_to_dict(overlay: TextOverlay) -> dict:
    return asdict(overlay)


def overlay_from_dict(data: dict) -> TextOverlay:
    base = asdict(default_title_overlay())
    base.update(data)
    if "first_line_font_size" not in data:
        font_size = int(base.get("font_size", 72) or 72)
        base["first_line_font_size"] = max(font_size + 16, int(font_size * 1.25))
    return TextOverlay(**{k: base[k] for k in asdict(default_title_overlay()).keys()})


def default_title_overlay() -> TextOverlay:
    return TextOverlay(
        id="title",
        label="Title Text",
        text_position="top",
        text_custom_y=120,
        font_size=72,
        first_line_font_size=92,
    )


def default_footer_overlay() -> TextOverlay:
    return TextOverlay(
        id="footer",
        label="Footer Text",
        text="Snooker 2026",
        text_position="bottom",
        text_custom_y=80,
        font_size=56,
        first_line_font_size=72,
        font_color="#FFFFFF",
        text_outline_enabled=True,
        outline_color="#000000",
        outline_size=3,
    )


def default_text_overlays() -> list[TextOverlay]:
    return [default_title_overlay(), default_footer_overlay()]


def migrate_settings_dict(data: dict) -> dict:
    if data.get("text_overlays"):
        overlays = list(data["text_overlays"])
        ids = {o.get("id") for o in overlays}
        if "footer" not in ids:
            overlays.append(overlay_to_dict(default_footer_overlay()))
        data["text_overlays"] = overlays
        data.setdefault("active_text_overlay_id", "title")
        return data

    title = default_title_overlay()
    title.text = data.get("text", "") or ""
    title.text_case = data.get("text_case", "none") or "none"
    title.text_spans = data.get("text_spans", []) or []
    title.first_line_color = data.get("first_line_color", "#FFD700") or "#FFD700"
    title.text_position = data.get("text_position", "top") or "top"
    title.text_custom_x = int(data.get("text_custom_x", 0) or 0)
    title.text_custom_y = int(data.get("text_custom_y", 120) or 120)
    title.font_size = int(data.get("font_size", 72) or 72)
    title.first_line_font_size = int(
        data.get("first_line_font_size", max(title.font_size + 16, int(title.font_size * 1.25))) or title.font_size
    )
    title.font_color = data.get("font_color", "#FFFFFF") or "#FFFFFF"
    title.font_path = data.get("font_path", DEFAULT_FONT) or DEFAULT_FONT
    title.text_box_enabled = bool(data.get("text_box_enabled", False))
    title.text_box_color = data.get("text_box_color", "#000000") or "#000000"
    title.text_box_opacity = float(data.get("text_box_opacity", 0.5) or 0.5)
    title.text_shadow_enabled = bool(data.get("text_shadow_enabled", True))
    title.text_outline_enabled = bool(data.get("text_outline_enabled", True))
    title.outline_color = data.get("outline_color", "#000000") or "#000000"
    title.outline_size = int(data.get("outline_size", 4) or 4)
    data["text_overlays"] = [overlay_to_dict(title), overlay_to_dict(default_footer_overlay())]
    data["active_text_overlay_id"] = data.get("active_text_overlay_id", "title")
    return data


def get_text_overlays(settings: EditorSettings) -> list[TextOverlay]:
    if settings.text_overlays:
        return [overlay_from_dict(item) for item in settings.text_overlays]
    return default_text_overlays()


def apply_text_case(text: str, case: str) -> str:
    if not text or case == "none":
        return text
    if case == "uppercase":
        return text.upper()
    if case == "lowercase":
        return text.lower()
    if case == "title":
        return text.title()
    if case == "sentence":
        lines: list[str] = []
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            stripped = line.strip()
            if not stripped:
                lines.append(line)
                continue
            lines.append(stripped[0].upper() + stripped[1:].lower() if len(stripped) > 1 else stripped.upper())
        return "\n".join(lines)
    return text


@dataclass
class TextSpan:
    text: str
    color: str


@dataclass
class DrawTextItem:
    text: str
    x: int
    y: int
    color: str
    font_size: int


def normalize_hex_color(color: str) -> str:
    color = color.strip().upper()
    if not color.startswith("#"):
        color = f"#{color}"
    return color


def color_to_tag(color: str) -> str:
    return f"c_{normalize_hex_color(color)[1:]}"


def tag_to_color(tag: str, default_color: str) -> str:
    if tag.startswith("c_") and len(tag) >= 8:
        return f"#{tag[2:].upper()}"
    return normalize_hex_color(default_color)


def ensure_color_tag(widget: tk.Text, color: str) -> str:
    tag = color_to_tag(color)
    if tag not in widget.tag_names():
        widget.tag_configure(tag, foreground=normalize_hex_color(color))
    return tag


def remove_color_tags_from_range(widget: tk.Text, start: str, end: str) -> None:
    for tag in widget.tag_names():
        if tag.startswith("c_"):
            widget.tag_remove(tag, start, end)


def apply_color_to_range(widget: tk.Text, start: str, end: str, color: str) -> None:
    if widget.compare(start, ">=", end):
        return
    remove_color_tags_from_range(widget, start, end)
    tag = ensure_color_tag(widget, color)
    widget.tag_add(tag, start, end)


def extract_text_spans(widget: tk.Text, default_color: str) -> list[TextSpan]:
    content = widget.get("1.0", "end-1c")
    if not content:
        return []
    default_color = normalize_hex_color(default_color)
    spans: list[TextSpan] = []
    i = 0
    n = len(content)
    while i < n:
        idx = widget.index(f"1.0 + {i} chars")
        color = default_color
        for tag in widget.tag_names(idx):
            if tag.startswith("c_"):
                color = tag_to_color(tag, default_color)
                break
        j = i + 1
        while j < n:
            idx_j = widget.index(f"1.0 + {j} chars")
            next_color = default_color
            for tag in widget.tag_names(idx_j):
                if tag.startswith("c_"):
                    next_color = tag_to_color(tag, default_color)
                    break
            if next_color != color:
                break
            j += 1
        spans.append(TextSpan(text=content[i:j], color=color))
        i = j
    return spans


def apply_spans_to_widget(widget: tk.Text, spans: list[TextSpan], default_color: str) -> None:
    widget.delete("1.0", tk.END)
    for span in spans:
        if not span.text:
            continue
        start = widget.index(tk.INSERT)
        widget.insert(tk.INSERT, span.text)
        end = widget.index(tk.INSERT)
        apply_color_to_range(widget, start, end, span.color or default_color)


def spans_from_overlay(overlay: TextOverlay) -> list[TextSpan]:
    if overlay.text_spans:
        return [
            TextSpan(s["text"], normalize_hex_color(s.get("color", overlay.font_color)))
            for s in overlay.text_spans
        ]
    if overlay.text.strip():
        return [TextSpan(overlay.text, normalize_hex_color(overlay.font_color))]
    return []


def spans_from_settings(settings: EditorSettings) -> list[TextSpan]:
    overlays = get_text_overlays(settings)
    if overlays:
        return spans_from_overlay(overlays[0])
    if settings.text_spans:
        return [TextSpan(s["text"], normalize_hex_color(s.get("color", settings.font_color))) for s in settings.text_spans]
    if settings.text.strip():
        return [TextSpan(settings.text, normalize_hex_color(settings.font_color))]
    return []


def spans_to_lines(spans: list[TextSpan]) -> list[list[TextSpan]]:
    lines: list[list[TextSpan]] = [[]]
    for span in spans:
        parts = span.text.split("\n")
        for index, part in enumerate(parts):
            if part:
                lines[-1].append(TextSpan(part, span.color))
            if index < len(parts) - 1:
                lines.append([])
    if lines == [[]]:
        return []
    return lines


def load_font_for_overlay(overlay: TextOverlay) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return load_font(overlay.font_path, overlay.font_size)


def load_font(font_path: str, font_size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(font_path, max(8, font_size))
    except OSError:
        return ImageFont.load_default()


def layout_colored_text(
    overlay: TextOverlay, spans: list[TextSpan]
) -> tuple[list[DrawTextItem], ElementRect | None]:
    if not spans:
        return [], None

    processed = [
        TextSpan(apply_text_case(span.text, overlay.text_case), normalize_hex_color(span.color))
        for span in spans
    ]
    lines = spans_to_lines(processed)
    if not lines:
        return [], None

    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    first_size = max(8, overlay.first_line_font_size or overlay.font_size)
    normal_size = max(8, overlay.font_size)
    line_spacing = max(4, max(first_size, normal_size) // 10)

    line_widths: list[int] = []
    line_heights: list[int] = []
    line_parts: list[list[tuple[str, int, str, int]]] = []

    for line_index, line in enumerate(lines):
        line_font_size = first_size if line_index == 0 else normal_size
        font = load_font(overlay.font_path, line_font_size)
        parts: list[tuple[str, int, str, int]] = []
        width = 0
        height = 0
        for span in line:
            bbox = measure.textbbox((0, 0), span.text, font=font)
            part_w = bbox[2] - bbox[0]
            part_h = bbox[3] - bbox[1]
            parts.append((span.text, part_w, span.color, line_font_size))
            width += part_w
            height = max(height, part_h)
        line_parts.append(parts)
        line_widths.append(width)
        line_heights.append(height)

    total_h = sum(line_heights) + line_spacing * max(0, len(lines) - 1)
    max_w = max(line_widths, default=0)

    if overlay.text_position == "top":
        x_base = (CANVAS_WIDTH - max_w) // 2
        y = overlay.text_custom_y
    elif overlay.text_position == "center":
        x_base = (CANVAS_WIDTH - max_w) // 2
        y = (CANVAS_HEIGHT - total_h) // 2
    elif overlay.text_position == "bottom":
        x_base = (CANVAS_WIDTH - max_w) // 2
        y = CANVAS_HEIGHT - total_h - overlay.text_custom_y
    elif overlay.text_position == "custom":
        x_base = overlay.text_custom_x
        y = overlay.text_custom_y
    else:
        x_base = (CANVAS_WIDTH - max_w) // 2
        y = overlay.text_custom_y

    box_pad = 16 if overlay.text_box_enabled else 0
    text_rect = ElementRect(
        x_base - box_pad,
        y - box_pad,
        max_w + box_pad * 2,
        total_h + box_pad * 2,
    )

    items: list[DrawTextItem] = []
    cy = y
    for parts, line_w, line_h in zip(line_parts, line_widths, line_heights):
        cx = x_base + (max_w - line_w) // 2
        for text, part_w, color, font_size in parts:
            items.append(DrawTextItem(text=text, x=cx, y=cy, color=color, font_size=font_size))
            cx += part_w
        cy += line_h + line_spacing

    return items, text_rect


def build_colored_drawtext_filters(overlay: TextOverlay, spans: list[TextSpan]) -> list[str]:
    items, _ = layout_colored_text(overlay, spans)
    if not items:
        return []

    font = escape_filter_path(overlay.font_path)
    filters: list[str] = []
    for item in items:
        if not item.text:
            continue
        draw_parts = [
            f"fontfile='{font}'",
            f"fontsize={max(8, item.font_size)}",
            f"fontcolor={hex_to_ffmpeg_color(item.color)}",
            f"x={item.x}",
            f"y={item.y}",
            f"text='{escape_drawtext_text(item.text)}'",
        ]
        if overlay.text_shadow_enabled:
            draw_parts.append("shadowx=3")
            draw_parts.append("shadowy=3")
            draw_parts.append("shadowcolor=0x000000@0.55")
        if overlay.text_outline_enabled:
            draw_parts.append(f"borderw={max(1, overlay.outline_size)}")
            draw_parts.append(f"bordercolor={hex_to_ffmpeg_color(overlay.outline_color)}")
        filters.append("drawtext=" + ":".join(draw_parts))
    return filters


# ---------------------------------------------------------------------------
# Settings / preset persistence
# ---------------------------------------------------------------------------


class SettingsManager:
    def __init__(self, path: Path = SETTINGS_PATH) -> None:
        self.path = path

    def load(self) -> EditorSettings:
        if not self.path.exists():
            settings = default_settings()
            self.save(settings)
            return settings
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            base = asdict(default_settings())
            base.update(data)
            base = migrate_settings_dict(base)
            return EditorSettings(**{k: base[k] for k in asdict(EditorSettings()).keys()})
        except (json.JSONDecodeError, TypeError, KeyError):
            return default_settings()

    def save(self, settings: EditorSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(asdict(settings), fh, indent=2, ensure_ascii=False)

    def save_preset(self, name: str, settings: EditorSettings) -> Path:
        PRESETS_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r'[<>:"/\\|?*]', "_", name.strip()) or "preset"
        path = PRESETS_DIR / f"{safe_name}.json"
        payload = asdict(settings)
        payload.pop("video_path", None)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"name": name, "settings": payload}, fh, indent=2, ensure_ascii=False)
        return path

    def list_presets(self) -> list[tuple[str, Path]]:
        if not PRESETS_DIR.exists():
            return []
        presets: list[tuple[str, Path]] = []
        for path in sorted(PRESETS_DIR.glob("*.json")):
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
                name = data.get("name", path.stem)
            except (json.JSONDecodeError, OSError):
                name = path.stem
            presets.append((name, path))
        return presets

    def load_preset(self, path: Path) -> EditorSettings:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        payload = data.get("settings", data)
        current = asdict(default_settings())
        current.update(payload)
        current = migrate_settings_dict(current)
        return EditorSettings(**{k: current[k] for k in asdict(EditorSettings()).keys()})


# ---------------------------------------------------------------------------
# FFmpeg helpers
# ---------------------------------------------------------------------------


def find_ffmpeg_executable() -> str | None:
    for name in ("ffmpeg", "ffmpeg.exe"):
        found = shutil.which(name)
        if found:
            return found

    home = Path.home()
    candidate_paths = [
        home / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe",
    ]

    local_appdata = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    for path in candidate_paths:
        if path.is_file():
            return str(path)

    candidate_globs = [
        "Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg-*/bin/ffmpeg.exe",
        "CapCut/Apps/*/ffmpeg.exe",
    ]
    for pattern in candidate_globs:
        matches = sorted(local_appdata.glob(pattern), reverse=True)
        for path in matches:
            if path.is_file():
                return str(path)
    return None


def check_ffmpeg() -> tuple[bool, str]:
    ffmpeg = find_ffmpeg_executable()
    if not ffmpeg:
        return False, (
            "FFmpeg was not found.\n\n"
            "Install FFmpeg for Windows, or add its bin folder to PATH, then restart the app."
        )
    return True, ffmpeg


def find_ffprobe_executable(ffmpeg_path: str | None = None) -> str | None:
    for name in ("ffprobe", "ffprobe.exe"):
        found = shutil.which(name)
        if found:
            return found
    if ffmpeg_path:
        sibling = Path(ffmpeg_path).with_name("ffprobe.exe")
        if sibling.is_file():
            return str(sibling)
    return None


def video_has_audio_stream(path: str, ffmpeg_path: str | None = None) -> bool:
    ffprobe = find_ffprobe_executable(ffmpeg_path)
    if not ffprobe:
        return True
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    return bool(result.stdout.strip())


def hex_to_ffmpeg_color(color: str) -> str:
    color = color.strip()
    if color.startswith("#"):
        return "0x" + color[1:]
    return color


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.strip().lstrip("#")
    if len(color) != 6:
        return 0, 0, 0
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def escape_filter_path(path: str) -> str:
    normalized = Path(path).as_posix()
    return normalized.replace(":", r"\:").replace("'", r"\'")


def escape_drawtext_text(text: str) -> str:
    escaped = text.replace("\\", "\\\\")
    escaped = escaped.replace(":", r"\:")
    escaped = escaped.replace("'", r"\'")
    escaped = escaped.replace("%", r"\%")
    return escaped


def build_pad_x(position: str, custom_x: int) -> str:
    if position == "custom":
        return str(max(0, custom_x))
    return "(ow-iw)/2"


def build_pad_y(position: str, custom_y: int) -> str:
    if position == "top":
        return str(max(0, custom_y))
    if position == "bottom":
        return f"oh-ih-{max(0, custom_y)}"
    if position == "custom":
        return str(max(0, custom_y))
    return "(oh-ih)/2"


def get_video_dimensions(path: str) -> tuple[int, int]:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return 0, 0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()
    return w, h


def get_video_duration(path: str) -> float:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return 0.0
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
    cap.release()
    if fps <= 0 or frame_count <= 0:
        return 0.0
    return frame_count / fps


ZOOM_MIN = 0.5
ZOOM_MAX = 4.0
UNDO_LIMIT = 10


@dataclass
class VideoLayout:
    fit_w: int
    fit_h: int
    crop_x: int = 0
    crop_y: int = 0
    pad_x: int = 0
    pad_y: int = 0
    output_w: int = CANVAS_WIDTH
    output_h: int = CANVAS_HEIGHT

    @property
    def is_cropped(self) -> bool:
        return self.fit_w > self.output_w or self.fit_h > self.output_h

    @property
    def visible_w(self) -> int:
        return min(self.fit_w, self.output_w)

    @property
    def visible_h(self) -> int:
        return min(self.fit_h, self.output_h)


def compute_video_layout(src_w: int, src_h: int, settings: EditorSettings) -> VideoLayout:
    """Compute scaled video size and placement on the vertical canvas."""
    if src_w <= 0 or src_h <= 0:
        return VideoLayout(CANVAS_WIDTH, CANVAS_HEIGHT)

    zoom = max(0.1, min(settings.video_scale, ZOOM_MAX))

    if settings.crop_mode:
        cover_scale = max(CANVAS_WIDTH / src_w, CANVAS_HEIGHT / src_h) * zoom
        fit_w = max(1, int(src_w * cover_scale))
        fit_h = max(1, int(src_h * cover_scale))
        crop_x, crop_y = _crop_origin(settings, fit_w, fit_h)
        return VideoLayout(fit_w, fit_h, crop_x, crop_y, 0, 0)

    base_scale = min(CANVAS_WIDTH / src_w, CANVAS_HEIGHT / src_h)
    fit_w = max(1, int(src_w * base_scale * zoom))
    fit_h = max(1, int(src_h * base_scale * zoom))
    pad_x, pad_y = _pad_position(settings, fit_w, fit_h)
    return VideoLayout(fit_w, fit_h, 0, 0, pad_x, pad_y, CANVAS_WIDTH, CANVAS_HEIGHT)


def _crop_axis(settings: EditorSettings, axis: str, fit_size: int, canvas_size: int) -> int:
    max_crop = max(0, fit_size - canvas_size)
    if axis == "x" and settings.video_center_align:
        return max_crop // 2
    if settings.video_position == "custom":
        value = settings.video_custom_x if axis == "x" else settings.video_custom_y
        return max(0, min(value, max_crop))
    if axis == "y" and settings.video_position == "top":
        return 0
    if axis == "y" and settings.video_position == "bottom":
        return max_crop
    return max_crop // 2


def _crop_origin(settings: EditorSettings, fit_w: int, fit_h: int) -> tuple[int, int]:
    return (
        _crop_axis(settings, "x", fit_w, CANVAS_WIDTH),
        _crop_axis(settings, "y", fit_h, CANVAS_HEIGHT),
    )


def _pad_position(settings: EditorSettings, visible_w: int, visible_h: int) -> tuple[int, int]:
    if settings.video_position == "custom":
        x = (CANVAS_WIDTH - visible_w) // 2 if settings.video_center_align else settings.video_custom_x
        y = settings.video_custom_y
    elif settings.video_position == "top":
        x = (CANVAS_WIDTH - visible_w) // 2
        y = max(0, settings.video_custom_y)
    elif settings.video_position == "bottom":
        x = (CANVAS_WIDTH - visible_w) // 2
        y = max(0, CANVAS_HEIGHT - visible_h - settings.video_custom_y)
    else:
        x = (CANVAS_WIDTH - visible_w) // 2
        y = (CANVAS_HEIGHT - visible_h) // 2
    return x, y


def build_video_filters(layout: VideoLayout, bg: str) -> list[str]:
    """Build FFmpeg filters for scale, optional crop, and optional pad."""
    filters = [f"scale={layout.fit_w}:{layout.fit_h}"]
    current_w, current_h = layout.fit_w, layout.fit_h
    crop_x, crop_y = layout.crop_x, layout.crop_y
    target_w, target_h = layout.output_w, layout.output_h

    if current_w > target_w:
        filters.append(f"crop={target_w}:{current_h}:{crop_x}:0")
        current_w = target_w
        crop_x = 0

    if current_h > target_h:
        filters.append(f"crop={current_w}:{target_h}:0:{crop_y}")
        current_h = target_h

    if current_w < CANVAS_WIDTH or current_h < CANVAS_HEIGHT:
        filters.append(
            f"pad={CANVAS_WIDTH}:{CANVAS_HEIGHT}:{layout.pad_x}:{layout.pad_y}:{bg}"
        )
    return filters


def build_free_video_filtergraph(
    layout: VideoLayout,
    bg: str,
    post_filters: list[str],
    input_label: str = "0:v",
    output_label: str = "v",
) -> str:
    chain = [
        f"color=c={bg}:s={CANVAS_WIDTH}x{CANVAS_HEIGHT}:r=30[base]",
        f"[{input_label}]scale={layout.fit_w}:{layout.fit_h}[clip]",
        f"[base][clip]overlay=x={layout.pad_x}:y={layout.pad_y}:shortest=1[composite]",
    ]
    tail = ",".join(post_filters) if post_filters else "null"
    chain.append(f"[composite]{tail}[{output_label}]")
    return ";".join(chain)


def format_ffmpeg_seconds(value: float) -> str:
    return f"{max(0.0, value):.3f}".rstrip("0").rstrip(".") or "0"


def normalize_clip_trim(start: float, end: float, duration: float) -> tuple[float, float]:
    start = max(0.0, float(start or 0.0))
    end = max(0.0, float(end or 0.0))
    if duration > 0:
        start = min(start, max(0.0, duration - 0.001))
        if end <= 0.0 or end > duration:
            end = duration
        if end <= start:
            end = duration
    elif end > 0.0 and end <= start:
        end = 0.0
    return start, end


def build_trim_arg(start: float, end: float) -> str:
    parts = [f"start={format_ffmpeg_seconds(start)}"]
    if end > 0.0:
        parts.append(f"end={format_ffmpeg_seconds(end)}")
    return ":".join(parts)


def repeat_clip_output_duration(settings: EditorSettings, source_duration: float) -> float:
    if source_duration <= 0:
        return 0.0
    c1_start, c1_end = normalize_clip_trim(
        settings.clip1_trim_start,
        settings.clip1_trim_end,
        source_duration,
    )
    c2_start, c2_end = normalize_clip_trim(
        settings.clip2_trim_start,
        settings.clip2_trim_end,
        source_duration,
    )
    return max(0.0, c1_end - c1_start) + max(0.0, c2_end - c2_start)


def build_repeat_clip_filtergraph_prefix(
    settings: EditorSettings,
    source_duration: float,
    include_audio: bool,
) -> tuple[list[str], str, str | None]:
    c1_start, c1_end = normalize_clip_trim(
        settings.clip1_trim_start,
        settings.clip1_trim_end,
        source_duration,
    )
    c2_start, c2_end = normalize_clip_trim(
        settings.clip2_trim_start,
        settings.clip2_trim_end,
        source_duration,
    )
    c1 = build_trim_arg(c1_start, c1_end)
    c2 = build_trim_arg(c2_start, c2_end)

    parts = [
        f"[0:v]trim={c1},setpts=PTS-STARTPTS[segv1]",
        f"[0:v]trim={c2},setpts=PTS-STARTPTS[segv2]",
    ]
    if include_audio:
        parts.extend(
            [
                f"[0:a]atrim={c1},asetpts=PTS-STARTPTS[sega1]",
                f"[0:a]atrim={c2},asetpts=PTS-STARTPTS[sega2]",
                "[segv1][sega1][segv2][sega2]concat=n=2:v=1:a=1[repeatv][repeata]",
            ]
        )
        return parts, "repeatv", "repeata"

    parts.append("[segv1][segv2]concat=n=2:v=1:a=0[repeatv]")
    return parts, "repeatv", None


def build_end_sound_audio_filter(
    sound_input_index: int,
    audio_delay_ms: int,
    base_audio_label: str | None = "0:a",
    output_duration: float = 0.0,
) -> str:
    delayed = f"[{sound_input_index}:a]adelay={audio_delay_ms}|{audio_delay_ms},volume=1.30"
    if base_audio_label:
        return (
            f"{delayed}[clap];"
            f"[{base_audio_label}][clap]amix=inputs=2:duration=first:dropout_transition=0[a]"
        )
    if output_duration > 0:
        delayed += f",apad,atrim=0:{format_ffmpeg_seconds(output_duration)}"
    return f"{delayed}[a]"


def build_text_xy(position: str, custom_x: int, custom_y: int) -> tuple[str, str]:
    if position == "top":
        return "(w-text_w)/2", str(custom_y)
    if position == "center":
        return "(w-text_w)/2", "(h-text_h)/2"
    if position == "bottom":
        return "(w-text_w)/2", f"h-text_h-{custom_y}"
    if position == "custom":
        return str(custom_x), str(custom_y)
    return "(w-text_w)/2", str(custom_y)


def format_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    total = int(seconds)
    hrs, rem = divmod(total, 3600)
    mins, secs = divmod(rem, 60)
    if hrs:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def format_timeline_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    total = int(seconds)
    mins, secs = divmod(total, 60)
    return f"{mins}:{secs:02d}"


def parse_metadata_response(text: str) -> dict[str, str]:
    result = {"video_text": "", "title": "", "description": "", "tags": ""}
    pattern = re.compile(r"(?im)^\s*(video\s*top\s*text|video\s*text|top\s*text|overlay\s*text|title|description|tags)\s*:\s*")
    matches = list(pattern.finditer(text or ""))
    for index, match in enumerate(matches):
        raw_key = re.sub(r"\s+", " ", match.group(1).lower()).strip()
        key = "video_text" if raw_key in {"video text", "video top text", "top text", "overlay text"} else raw_key
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        result[key] = text[start:end].strip()
    if not any(result.values()):
        result["description"] = (text or "").strip()
    result["tags"] = ", ".join(
        part.strip().lstrip("#")
        for part in re.split(r"[,\n]+", result["tags"])
        if part.strip()
    )
    return result


def normalize_video_text(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if "\n" not in text and "|" in text:
        text = "\n".join(part.strip() for part in text.split("|", 1))
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) >= 2:
        return f"{lines[0]}\n{' '.join(lines[1:])}"
    return lines[0] if lines else ""


def parse_schedule_time(date_str: str, time_str: str) -> str:
    """Parses date and time strings and returns ISO 8601 UTC string."""
    date_str = date_str.strip()
    time_str = time_str.strip()
    if not date_str:
        raise ValueError("Date is required for scheduling.")
    if not time_str:
        time_str = "00:00"

    date_str = date_str.replace("/", "-").replace(".", "-")
    date_formats = ["%Y-%m-%d", "%d-%m-%Y", "%m-%d-%Y"]
    time_formats = ["%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M%p"]

    dt = None
    for df in date_formats:
        try:
            parsed_date = datetime.strptime(date_str, df)
            dt = parsed_date
            break
        except ValueError:
            continue

    if not dt:
        raise ValueError("Invalid date format. Please use YYYY-MM-DD.")

    parsed_time = None
    for tf in time_formats:
        try:
            parsed_time = datetime.strptime(time_str, tf).time()
            break
        except ValueError:
            continue

    if parsed_time is None:
        raise ValueError("Invalid time format. Please use HH:MM or HH:MM AM/PM.")

    dt = datetime.combine(dt.date(), parsed_time)
    dt_local = dt.astimezone()
    dt_utc = dt_local.astimezone(timezone.utc)

    if dt_utc <= datetime.now(timezone.utc):
        raise ValueError("Scheduled time must be in the future.")

    return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def call_openai_metadata(api_key: str, model: str, system_prompt: str, user_prompt: str) -> str:
    if not user_prompt:
        user_prompt = (
            "Generate YouTube Shorts metadata and a two-line video top text overlay for the currently edited short video."
        )
    payload = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": system_prompt,
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": user_prompt,
                    }
                ],
            },
        ],
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(detail or str(exc)) from exc
    payload = json.loads(body)
    if payload.get("output_text"):
        return payload["output_text"]
    chunks: list[str] = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(content["text"])
    return "\n".join(chunks).strip()


TIMELINE_THUMB_WIDTH = 14
TIMELINE_THUMB_HEIGHT = 18
TEXT_RESIZE_HANDLE = 28
FONT_SIZE_MIN = 16
FONT_SIZE_MAX = 240


class FFmpegBuilder:
    def __init__(self, settings: EditorSettings) -> None:
        self.settings = settings

    def validate(self) -> None:
        s = self.settings
        if not s.video_path or not Path(s.video_path).is_file():
            raise ValueError("No video selected. Choose a video file first.")
        ext = Path(s.video_path).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported video format '{ext}'.\n"
                f"Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )
        for overlay in get_text_overlays(s):
            if not overlay.font_path or not Path(overlay.font_path).is_file():
                raise ValueError(
                    f"Invalid font file for {overlay.label}.\n"
                    "Select a valid .ttf or .otf font from your system."
                )
        if not s.output_folder:
            raise ValueError("Output folder is not set.")
        out_dir = Path(s.output_folder)
        if not out_dir.exists():
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise ValueError(f"Output folder is missing and could not be created:\n{out_dir}") from exc
        if not s.output_filename.strip():
            raise ValueError("Output file name cannot be empty.")
        if s.end_sound_enabled and (not s.end_sound_path or not Path(s.end_sound_path).is_file()):
            raise ValueError("End sound effect is enabled, but the sound file was not found.")

    def build_command(self) -> list[str]:
        self.validate()
        s = self.settings
        ok, ffmpeg = check_ffmpeg()
        if not ok:
            raise RuntimeError(ffmpeg)

        bg = hex_to_ffmpeg_color(s.background_color)
        src_w, src_h = get_video_dimensions(s.video_path)

        layout = compute_video_layout(src_w, src_h, s)
        video_filters = build_video_filters(layout, bg) if s.crop_mode else []
        overlay_filters: list[str] = []

        for overlay in get_text_overlays(s):
            spans = spans_from_overlay(overlay)
            if not spans:
                continue
            if overlay.text_box_enabled:
                _, text_rect = layout_colored_text(overlay, spans)
                if text_rect is not None:
                    box_color = hex_to_ffmpeg_color(overlay.text_box_color)
                    opacity = max(0.0, min(overlay.text_box_opacity, 1.0))
                    overlay_filters.append(
                        f"drawbox=x={text_rect.x}:y={text_rect.y}:w={text_rect.w}:h={text_rect.h}:"
                        f"color={box_color}@{opacity:.2f}:t=fill"
                    )
            overlay_filters.extend(build_colored_drawtext_filters(overlay, spans))

        vf = ",".join(video_filters + overlay_filters)
        quality = QUALITY_PRESETS.get(s.export_quality, QUALITY_PRESETS["balanced"])

        cmd = [
            ffmpeg,
            "-y",
            "-i",
            s.video_path,
        ]
        use_end_sound = s.end_sound_enabled and bool(s.end_sound_path) and Path(s.end_sound_path).is_file()
        use_repeat = bool(s.repeat_clip_twice)
        source_duration = get_video_duration(s.video_path) if (use_repeat or use_end_sound) else 0.0
        output_duration = repeat_clip_output_duration(s, source_duration) if use_repeat else source_duration
        audio_delay_ms = 0
        if use_end_sound:
            start_at = max(0.0, output_duration - max(0.0, float(s.end_sound_start_before_end)))
            audio_delay_ms = int(start_at * 1000)
            cmd.extend(["-i", s.end_sound_path])

        if use_repeat:
            include_audio = video_has_audio_stream(s.video_path, ffmpeg)
            filter_parts, source_video_label, source_audio_label = build_repeat_clip_filtergraph_prefix(
                s,
                source_duration,
                include_audio,
            )
            if s.crop_mode:
                tail = ",".join(video_filters + overlay_filters) if (video_filters or overlay_filters) else "null"
                filter_parts.append(f"[{source_video_label}]{tail}[v]")
            else:
                filter_parts.append(
                    build_free_video_filtergraph(
                        layout,
                        bg,
                        overlay_filters,
                        input_label=source_video_label,
                    )
                )
            if use_end_sound:
                filter_parts.append(
                    build_end_sound_audio_filter(
                        1,
                        audio_delay_ms,
                        base_audio_label=source_audio_label,
                        output_duration=output_duration,
                    )
                )
            cmd.extend(["-filter_complex", ";".join(filter_parts), "-map", "[v]"])
            if use_end_sound:
                cmd.extend(["-map", "[a]"])
            elif source_audio_label:
                cmd.extend(["-map", f"[{source_audio_label}]"])
        elif s.crop_mode:
            if use_end_sound:
                audio_graph = build_end_sound_audio_filter(1, audio_delay_ms, base_audio_label="0:a")
                cmd.extend(["-vf", vf, "-filter_complex", audio_graph, "-map", "0:v", "-map", "[a]"])
            else:
                cmd.extend(["-vf", vf, "-map", "0:v", "-map", "0:a?"])
        else:
            filtergraph = build_free_video_filtergraph(layout, bg, overlay_filters)
            if use_end_sound:
                filtergraph += ";" + build_end_sound_audio_filter(1, audio_delay_ms, base_audio_label="0:a")
            cmd.extend(
                [
                    "-filter_complex",
                    filtergraph,
                    "-map",
                    "[v]",
                    "-map",
                    "[a]" if use_end_sound else "0:a?",
                ]
            )
        cmd.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                quality["preset"],
                "-crf",
                quality["crf"],
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                str(Path(s.output_folder) / f"{s.output_filename.strip()}.mp4"),
            ]
        )
        return cmd

    def output_path(self) -> Path:
        return Path(self.settings.output_folder) / f"{self.settings.output_filename.strip()}.mp4"


# ---------------------------------------------------------------------------
# Live preview engine
# ---------------------------------------------------------------------------


@dataclass
class ElementRect:
    x: int
    y: int
    w: int
    h: int


@dataclass
class TextOverlayRect:
    overlay_id: str
    label: str
    rect: ElementRect


@dataclass
class ComposeResult:
    image: Image.Image
    video_rect: ElementRect | None = None
    text_rects: list[TextOverlayRect] = field(default_factory=list)
    video_layout: VideoLayout | None = None


class PreviewCompositor:
    """Renders the vertical canvas preview to match FFmpeg export logic."""

    @staticmethod
    def compose(frame_bgr: np.ndarray, settings: EditorSettings) -> ComposeResult:
        src_h, src_w = frame_bgr.shape[:2]
        video_rect: ElementRect | None = None

        layout = compute_video_layout(src_w, src_h, settings)
        fitted = cv2.resize(frame_bgr, (layout.fit_w, layout.fit_h), interpolation=cv2.INTER_AREA)
        frame_rgb = Image.fromarray(cv2.cvtColor(fitted, cv2.COLOR_BGR2RGB))

        canvas = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), hex_to_rgb(settings.background_color))
        if settings.crop_mode:
            x1 = layout.crop_x
            y1 = layout.crop_y
            x2 = x1 + layout.visible_w
            y2 = y1 + layout.visible_h
            visible = frame_rgb.crop((x1, y1, x2, y2))
            canvas.paste(visible, (layout.pad_x, layout.pad_y))
            video_rect = ElementRect(layout.pad_x, layout.pad_y, layout.visible_w, layout.visible_h)
        else:
            PreviewCompositor._paste_layer(canvas, frame_rgb, layout.pad_x, layout.pad_y)
            video_rect = ElementRect(layout.pad_x, layout.pad_y, layout.fit_w, layout.fit_h)


        text_rects = PreviewCompositor._draw_text(canvas, settings)
        return ComposeResult(
            image=canvas,
            video_rect=video_rect,
            text_rects=text_rects,
            video_layout=layout,
        )

    @staticmethod
    def _paste_layer(canvas: Image.Image, layer: Image.Image, x: int, y: int) -> None:
        src_x1 = max(0, -x)
        src_y1 = max(0, -y)
        dst_x1 = max(0, x)
        dst_y1 = max(0, y)
        dst_x2 = min(canvas.width, x + layer.width)
        dst_y2 = min(canvas.height, y + layer.height)
        if dst_x2 <= dst_x1 or dst_y2 <= dst_y1:
            return
        src_x2 = src_x1 + (dst_x2 - dst_x1)
        src_y2 = src_y1 + (dst_y2 - dst_y1)
        canvas.paste(layer.crop((src_x1, src_y1, src_x2, src_y2)), (dst_x1, dst_y1))

    @staticmethod
    def _draw_text(canvas: Image.Image, settings: EditorSettings) -> list[TextOverlayRect]:
        rects: list[TextOverlayRect] = []
        for overlay in get_text_overlays(settings):
            spans = spans_from_overlay(overlay)
            if not spans:
                continue

            items, text_rect = layout_colored_text(overlay, spans)
            if not items or text_rect is None:
                continue

            draw = ImageDraw.Draw(canvas)

            if overlay.text_box_enabled:
                box_rgb = hex_to_rgb(overlay.text_box_color)
                alpha = int(max(0.0, min(overlay.text_box_opacity, 1.0)) * 255)
                box_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
                box_draw = ImageDraw.Draw(box_layer)
                box_draw.rectangle(
                    [text_rect.x, text_rect.y, text_rect.x + text_rect.w, text_rect.y + text_rect.h],
                    fill=(*box_rgb, alpha),
                )
                composed = Image.alpha_composite(canvas.convert("RGBA"), box_layer)
                canvas.paste(composed.convert("RGB"))
                draw = ImageDraw.Draw(canvas)

            stroke_w = overlay.outline_size if overlay.text_outline_enabled else 0
            stroke_fill = hex_to_rgb(overlay.outline_color) if overlay.text_outline_enabled else None

            for item in items:
                font = load_font(overlay.font_path, item.font_size)
                fill = hex_to_rgb(item.color)
                if overlay.text_shadow_enabled:
                    draw.text((item.x + 3, item.y + 3), item.text, font=font, fill=(0, 0, 0))
                draw.text(
                    (item.x, item.y),
                    item.text,
                    font=font,
                    fill=fill,
                    stroke_width=stroke_w,
                    stroke_fill=stroke_fill,
                )

            rects.append(TextOverlayRect(overlay.id, overlay.label, text_rect))
        return rects


class VideoPreviewEngine:
    def __init__(self) -> None:
        self.cap: cv2.VideoCapture | None = None
        self.video_path = ""
        self.fps = 30.0
        self.frame_count = 0
        self.current_frame_idx = 0
        self.duration_sec = 0.0
        self.playing = False
        self._lock = threading.Lock()

    def load(self, path: str) -> bool:
        self.stop()
        with self._lock:
            if self.cap is not None:
                self.cap.release()
                self.cap = None
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                return False
            self.cap = cap
            self.video_path = path
            self.fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
            if self.fps <= 0:
                self.fps = 30.0
            self.frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            self.duration_sec = self.frame_count / self.fps if self.frame_count > 0 else 0.0
            self.current_frame_idx = 0
            return True

    def release(self) -> None:
        self.stop()
        with self._lock:
            if self.cap is not None:
                self.cap.release()
                self.cap = None

    def stop(self) -> None:
        self.playing = False

    def is_loaded(self) -> bool:
        return self.cap is not None and self.cap.isOpened()

    def seek(self, frame_idx: int) -> np.ndarray | None:
        if not self.is_loaded():
            return None
        max_idx = max(0, self.frame_count - 1)
        frame_idx = max(0, min(frame_idx, max_idx))
        with self._lock:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ok, frame = self.cap.read()
            if ok:
                self.current_frame_idx = frame_idx
                return frame
        return None

    def current_time(self) -> float:
        return self.current_frame_idx / self.fps if self.fps > 0 else 0.0


# ---------------------------------------------------------------------------
# Windows drag-and-drop (optional, no extra packages)
# ---------------------------------------------------------------------------


def enable_windows_drag_drop(widget: tk.Misc, callback) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        WM_DROPFILES = 0x0233

        def py_drop_handler(hwnd, msg, wparam, lparam):
            if msg == WM_DROPFILES:
                count = ctypes.windll.shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                paths: list[str] = []
                for i in range(count):
                    length = ctypes.windll.shell32.DragQueryFileW(wparam, i, None, 0) + 1
                    buffer = ctypes.create_unicode_buffer(length)
                    ctypes.windll.shell32.DragQueryFileW(wparam, i, buffer, length)
                    paths.append(buffer.value)
                ctypes.windll.shell32.DragFinish(wparam)
                if paths:
                    callback(paths[0])
                return 0
            return ctypes.windll.user32.CallWindowProcW(old_proc, hwnd, msg, wparam, lparam)

        hwnd = widget.winfo_id()
        ctypes.windll.shell32.DragAcceptFiles(hwnd, True)
        prototype = ctypes.WINFUNCTYPE(
            wintypes.LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )
        handler = prototype(py_drop_handler)
        old_proc = ctypes.windll.user32.SetWindowLongPtrW(hwnd, -4, handler)
        widget._dnd_handler = handler
        widget._dnd_old_proc = old_proc
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Main application UI
# ---------------------------------------------------------------------------


class VideoEditorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Shorts Maker")
        self.root.minsize(1080, 720)
        self.root.geometry("1440x900")

        self.settings_manager = SettingsManager()
        self.settings = self.settings_manager.load()
        self.preview_engine = VideoPreviewEngine()
        self.export_thread: threading.Thread | None = None
        self._suspend_save = False
        self._suspend_zoom_sync = False
        self._preview_photo: ImageTk.PhotoImage | None = None
        self._preview_after_id: str | None = None
        self._preview_resize_after_id: str | None = None
        self.preview_display_w = PREVIEW_DISPLAY_W
        self.preview_display_h = PREVIEW_DISPLAY_H
        self._play_after_id: str | None = None
        self._play_started_at = 0.0
        self._play_start_frame_idx = 0
        self._scrubbing = False
        self._compose_layout: ComposeResult | None = None
        self._drag_target: str | None = None
        self._drag_offset_x = 0
        self._drag_offset_y = 0
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []
        self._suspend_undo = False
        self._undo_pending_snapshot: dict | None = None
        self._undo_push_after: str | None = None
        self._overlay_widgets: dict[str, scrolledtext.ScrolledText] = {}
        self._overlay_frames: dict[str, tk.LabelFrame] = {}
        self._active_overlay_id = "title"
        self._suspend_overlay_switch = False
        self._overlay_combo_to_id = {"Title Text": "title", "Footer Text": "footer"}
        self._overlay_id_to_combo = {"title": "Title Text", "footer": "Footer Text"}
        self._drag_overlay_id: str | None = None
        self._drag_origin_font_size = 72
        self._drag_origin_rect_h = 1
        self._active_section = "video"
        self._section_frames: dict[str, ttk.Frame] = {}
        self._section_buttons: dict[str, ttk.Button] = {}

        self._build_style()
        self._build_ui()
        self._apply_settings_to_ui()
        self._bind_events()
        self.root.after(0, self._maximize_for_editing)

        ok, msg = check_ffmpeg()
        if not ok:
            self.set_status("Warning: FFmpeg not found", error=True)
            messagebox.showwarning("FFmpeg Missing", msg)
        else:
            self.set_status("Ready. Select a video to see the live preview.")

        if enable_windows_drag_drop(self.root, self._on_video_dropped):
            self.set_status("Ready. Drag and drop a video file is supported.")

        if self.settings.video_path and Path(self.settings.video_path).is_file():
            self._load_video_preview(self.settings.video_path, show_error=False)

        if HAS_GOOGLE_API:
            self.root.after(500, self._check_existing_youtube_auth)

    def _maximize_for_editing(self) -> None:
        try:
            self.root.state("zoomed")
        except tk.TclError:
            pass

    def _build_style(self) -> None:
        self.root.configure(bg=THEME["bg"])
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(".", background=THEME["bg"], foreground=THEME["text"], font=("Segoe UI", 10))
        style.configure("TFrame", background=THEME["bg"])
        style.configure("Card.TFrame", background=THEME["surface"])
        style.configure("TLabel", background=THEME["bg"], foreground=THEME["text"])
        style.configure("Card.TLabel", background=THEME["surface"], foreground=THEME["text"])
        style.configure("Muted.TLabel", background=THEME["bg"], foreground=THEME["text_muted"], font=("Segoe UI", 9))
        style.configure("CardMuted.TLabel", background=THEME["surface"], foreground=THEME["text_muted"], font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=THEME["bg"], foreground=THEME["text"], font=("Segoe UI", 22, "bold"))
        style.configure("Subtitle.TLabel", background=THEME["bg"], foreground=THEME["text_muted"], font=("Segoe UI", 10))

        style.configure("TLabelframe", background=THEME["surface"], bordercolor=THEME["border"], relief="solid", borderwidth=1)
        style.configure("TLabelframe.Label", background=THEME["surface"], foreground=THEME["accent"], font=("Segoe UI", 10, "bold"))
        style.configure("Card.TLabelframe", background=THEME["surface"], bordercolor=THEME["border"], relief="solid", borderwidth=1)
        style.configure("Card.TLabelframe.Label", background=THEME["surface"], foreground=THEME["accent"], font=("Segoe UI", 10, "bold"))
        style.configure("Sub.TLabelframe", background=THEME["surface"], bordercolor=THEME["border"], relief="solid", borderwidth=1)
        style.configure("Sub.TLabelframe.Label", background=THEME["surface"], foreground=THEME["text_muted"], font=("Segoe UI", 9, "bold"))

        style.configure("TButton", background=THEME["surface2"], foreground=THEME["text"], borderwidth=0, padding=(12, 7))
        style.map("TButton", background=[("active", THEME["border"]), ("pressed", THEME["border"])])

        style.configure(
            "Accent.TButton",
            background=THEME["accent"],
            foreground="#ffffff",
            font=("Segoe UI", 10, "bold"),
            padding=(18, 10),
            borderwidth=1,
            relief="raised",
        )
        style.map(
            "Accent.TButton",
            background=[("active", THEME["accent_hover"]), ("pressed", THEME["accent_hover"])],
            foreground=[("disabled", "#c8ccd4")],
        )

        style.configure("Format.TButton", background=THEME["surface2"], foreground=THEME["text"], padding=(10, 5), font=("Segoe UI", 9, "bold"))
        style.map("Format.TButton", background=[("active", THEME["accent"]), ("pressed", THEME["accent"])])

        style.configure(
            "TEntry",
            fieldbackground=THEME["surface2"],
            foreground=THEME["text"],
            insertcolor=THEME["accent"],
            bordercolor=THEME["border"],
            lightcolor=THEME["border"],
            darkcolor=THEME["border"],
            padding=(4, 4),
        )
        style.configure(
            "TCombobox",
            fieldbackground=THEME["surface2"],
            foreground=THEME["text"],
            background=THEME["surface2"],
            selectbackground=THEME["surface2"],
            selectforeground=THEME["text"],
            bordercolor=THEME["border"],
            lightcolor=THEME["border"],
            darkcolor=THEME["border"],
            arrowcolor=THEME["text"],
            padding=(4, 4),
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", THEME["surface2"]), ("!disabled", THEME["surface2"])],
            foreground=[("readonly", THEME["text"]), ("!disabled", THEME["text"])],
            selectbackground=[("readonly", THEME["surface2"]), ("!disabled", THEME["surface2"])],
            selectforeground=[("readonly", THEME["text"]), ("!disabled", THEME["text"])],
            background=[("active", THEME["border"]), ("readonly", THEME["surface2"])],
            arrowcolor=[("disabled", THEME["text_muted"]), ("!disabled", THEME["text"])],
        )

        style.configure("TNotebook", background=THEME["bg"], borderwidth=0, tabmargins=(0, 4, 0, 0))
        style.configure("TNotebook.Tab", background=THEME["surface"], foreground=THEME["text_muted"], padding=(16, 9), font=("Segoe UI", 10))
        style.map("TNotebook.Tab", background=[("selected", THEME["surface2"])], foreground=[("selected", THEME["text"])])

        style.configure("TCheckbutton", background=THEME["surface"], foreground=THEME["text"])
        style.configure("Horizontal.TScale", background=THEME["surface"], troughcolor=THEME["surface2"])
        style.configure("TProgressbar", troughcolor=THEME["surface2"], background=THEME["accent"], borderwidth=0, thickness=6)
        style.configure("TPanedwindow", background=THEME["bg"])
        style.configure(
            "Vertical.TScrollbar",
            background=THEME["surface2"],
            troughcolor=THEME["surface"],
            bordercolor=THEME["border"],
            arrowcolor=THEME["text_muted"],
            darkcolor=THEME["surface2"],
            lightcolor=THEME["surface2"],
        )
        style.map("Vertical.TScrollbar", background=[("active", THEME["border"])])

    def _bind_scroll_mousewheel(self, canvas: tk.Canvas) -> None:
        def on_mousewheel(event) -> None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def on_enter(_event) -> None:
            canvas.bind_all("<MouseWheel>", on_mousewheel)

        def on_leave(_event) -> None:
            canvas.unbind_all("<MouseWheel>")

        canvas.bind("<Enter>", on_enter)
        canvas.bind("<Leave>", on_leave)

    def _embed_scrollable_frame(
        self, parent: tk.Misc, *, bg: str, expand: bool = False, padx: int = 0, pady: int = 0
    ) -> ttk.Frame:
        holder = tk.Frame(parent, bg=bg)
        pack_kwargs: dict = {"fill": tk.BOTH if expand else tk.X, "expand": expand}
        if padx or pady:
            pack_kwargs.update({"padx": padx, "pady": pady})
        holder.pack(**pack_kwargs)

        canvas = tk.Canvas(holder, bg=bg, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(holder, orient=tk.VERTICAL, command=canvas.yview, style="Vertical.TScrollbar")
        inner = ttk.Frame(canvas, style="Card.TFrame")

        def update_scroll_region(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        inner.bind("<Configure>", update_scroll_region)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def on_canvas_configure(event) -> None:
            canvas.itemconfigure(window_id, width=max(event.width, 1))

        canvas.bind("<Configure>", on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._bind_scroll_mousewheel(canvas)
        return inner

    def _wrap_tab_page(self, parent: ttk.Frame) -> ttk.Frame:
        scroll_inner = self._embed_scrollable_frame(parent, bg=THEME["surface"], expand=True)
        content = ttk.Frame(scroll_inner, padding=12, style="Card.TFrame")
        content.pack(fill=tk.BOTH, expand=True)
        return content

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=16)
        container.pack(fill=tk.BOTH, expand=True)

        self.footer = ttk.Frame(container)
        self.footer.pack(side=tk.BOTTOM, fill=tk.X)
        self.footer.columnconfigure(1, weight=1)
        self.status_var = tk.StringVar(value="")
        self.status_label = ttk.Label(
            self.footer,
            textvariable=self.status_var,
            style="Muted.TLabel",
            wraplength=760,
        )
        self.status_label.grid(row=0, column=1, sticky=tk.EW, padx=(12, 12))
        self.status_label.bind(
            "<Configure>",
            lambda event: self.status_label.configure(wraplength=max(360, event.width - 4)),
        )
        self.progress = ttk.Progressbar(self.footer, mode="indeterminate")
        self.progress.grid(row=1, column=0, columnspan=3, sticky=tk.EW, pady=(6, 0))
        self.progress.grid_remove()
        actions = ttk.Frame(self.footer)
        actions.grid(row=0, column=0, sticky=tk.W)
        actions.columnconfigure(1, weight=1)
        preset_row = ttk.Frame(actions)
        preset_row.grid(row=0, column=0, sticky=tk.W)
        ttk.Button(preset_row, text="Save Preset", command=self.save_preset).pack(side=tk.LEFT)
        ttk.Button(preset_row, text="Load Preset", command=self.load_preset).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(preset_row, text="Reset Defaults", command=self.reset_defaults).pack(side=tk.LEFT, padx=(8, 0))
        undo_btn = ttk.Button(preset_row, text="Undo", command=self.undo_action)
        undo_btn.pack(side=tk.LEFT, padx=(16, 4))
        self._create_tooltip(undo_btn, f"Undo last change (Ctrl+Z, up to {UNDO_LIMIT} steps)")
        redo_btn = ttk.Button(preset_row, text="Redo", command=self.redo_action)
        redo_btn.pack(side=tk.LEFT)
        self._create_tooltip(redo_btn, f"Redo undone change (Ctrl+Y, up to {UNDO_LIMIT} steps)")
        self.export_btn = ttk.Button(
            self.footer,
            text="Export Video",
            command=self.start_export,
            style="Accent.TButton",
        )
        self.export_btn.grid(row=0, column=2, sticky=tk.E)

        nav = ttk.Frame(container)
        nav.pack(side=tk.TOP, fill=tk.X, pady=(0, 10))
        nav.columnconfigure(3, weight=1)
        for col, (section_id, label) in enumerate(
            (
                ("video", "Video Editing"),
                ("description", "Description"),
                ("upload", "Upload to YouTube"),
            )
        ):
            btn = ttk.Button(nav, text=label, command=lambda sid=section_id: self._show_section(sid))
            btn.grid(row=0, column=col, sticky=tk.W, padx=(0 if col == 0 else 8, 0))
            self._section_buttons[section_id] = btn

        section_host = ttk.Frame(container)
        section_host.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        video_section = ttk.Frame(section_host)
        description_section = ttk.Frame(section_host)
        upload_section = ttk.Frame(section_host)
        self._section_frames = {
            "video": video_section,
            "description": description_section,
            "upload": upload_section,
        }

        header = ttk.Frame(video_section)
        # Header title text is intentionally hidden; top-level section buttons own this area.
        header.columnconfigure(0, weight=1)
        title_col = ttk.Frame(header)
        title_col.grid(row=0, column=0, sticky=tk.EW)
        ttk.Label(title_col, text="Shorts Maker", style="Title.TLabel").pack(anchor=tk.W)
        self.subtitle_label = ttk.Label(
            title_col,
            text="Create vertical 1080×1920 videos for YouTube Shorts, TikTok & Reels",
            style="Subtitle.TLabel",
            wraplength=680,
        )
        self.subtitle_label.pack(anchor=tk.W, fill=tk.X, pady=(2, 0))
        self.subtitle_label.bind(
            "<Configure>",
            lambda event: self.subtitle_label.configure(wraplength=max(320, event.width - 4)),
        )

        body = ttk.Panedwindow(video_section, orient=tk.HORIZONTAL)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        left_outer = ttk.Frame(body)
        right = ttk.Frame(body, padding=(10, 0, 0, 0))
        body.add(left_outer, weight=2)
        body.add(right, weight=4)
        try:
            body.paneconfigure(left_outer, minsize=500)
            body.paneconfigure(right, minsize=520)
        except tk.TclError:
            pass
        left = self._embed_scrollable_frame(left_outer, bg=THEME["bg"], expand=True, padx=0, pady=0)

        video_frame = ttk.LabelFrame(left, text="  Video Input  ", padding=10, style="Card.TLabelframe")
        video_frame.pack(fill=tk.X, pady=(0, 10))
        video_row = ttk.Frame(video_frame, style="Card.TFrame")
        video_row.pack(fill=tk.X)
        video_row.columnconfigure(0, weight=1)
        self.video_path_var = tk.StringVar()
        ttk.Entry(video_row, textvariable=self.video_path_var).grid(row=0, column=0, sticky=tk.EW, ipady=4)
        ttk.Button(video_row, text="Browse", command=self.select_video).grid(row=0, column=1, padx=(8, 0))

        self.repeat_clip_twice_var = tk.BooleanVar(value=False)
        self.clip1_trim_start_var = tk.StringVar(value="0")
        self.clip1_trim_end_var = tk.StringVar(value="0")
        self.clip2_trim_start_var = tk.StringVar(value="0")
        self.clip2_trim_end_var = tk.StringVar(value="0")
        self.trim_summary_var = tk.StringVar(value="Clip 1: full | Clip 2: full")
        clip_row = ttk.Frame(video_frame, style="Card.TFrame")
        clip_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Checkbutton(
            clip_row,
            text="Repeat video twice",
            variable=self.repeat_clip_twice_var,
        ).pack(side=tk.LEFT)
        ttk.Button(clip_row, text="Trim Clips", command=self.open_trim_clips_dialog).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(
            clip_row,
            textvariable=self.trim_summary_var,
            style="CardMuted.TLabel",
            wraplength=360,
        ).pack(side=tk.LEFT, padx=(10, 0), fill=tk.X, expand=True)

        text_frame = ttk.LabelFrame(left, text="  Overlay Text  ", padding=10, style="Card.TLabelframe")
        text_frame.pack(fill=tk.X, pady=(0, 10))
        self.font_color_var = tk.StringVar(value="#FFFFFF")
        self.selection_color_var = tk.StringVar(value="#FF5555")
        self.first_line_color_var = tk.StringVar(value="#FFD700")

        text_tools_row = ttk.Frame(text_frame, style="Card.TFrame")
        text_tools_row.pack(fill=tk.X)
        text_tools_row.rowconfigure(0, weight=1)
        text_tools_row.columnconfigure(0, weight=1)
        text_tools_row.columnconfigure(1, weight=1)

        format_box = ttk.LabelFrame(text_tools_row, text="  Format  ", padding=8, style="Sub.TLabelframe")
        format_box.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 4))
        self._build_text_format_toolbar(format_box)

        color_box = ttk.LabelFrame(text_tools_row, text="  Colors  ", padding=8, style="Sub.TLabelframe")
        color_box.grid(row=0, column=1, sticky=tk.NSEW, padx=(4, 0))
        self._build_text_color_toolbar(color_box)

        layer_row = ttk.Frame(text_frame, style="Card.TFrame")
        layer_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(layer_row, text="Editing layer", style="CardMuted.TLabel").pack(side=tk.LEFT)
        self.active_overlay_var = tk.StringVar(value="title")
        self.active_overlay_combo = ttk.Combobox(
            layer_row,
            textvariable=self.active_overlay_var,
            state="readonly",
            width=18,
        )
        self.active_overlay_combo.pack(side=tk.LEFT, padx=(8, 0))
        self.active_overlay_combo.bind("<<ComboboxSelected>>", self._on_overlay_combo_selected)

        boxes_row = ttk.Frame(text_frame, style="Card.TFrame")
        boxes_row.pack(fill=tk.X, pady=(8, 0))
        boxes_row.rowconfigure(0, weight=1)
        boxes_row.columnconfigure(0, weight=1)
        boxes_row.columnconfigure(1, weight=1)
        for col, overlay_id in enumerate(("title", "footer")):
            self._create_overlay_text_box(boxes_row, overlay_id, col)

        tab_holder = tk.Frame(left, bg=THEME["bg"], height=420)
        tab_holder.pack(fill=tk.X, pady=(0, 10))
        tab_holder.pack_propagate(False)
        notebook = ttk.Notebook(tab_holder)
        notebook.pack(fill=tk.BOTH, expand=True)
        video_tab = ttk.Frame(notebook, style="Card.TFrame")
        text_tab = ttk.Frame(notebook, style="Card.TFrame")
        export_tab = ttk.Frame(notebook, style="Card.TFrame")
        notebook.add(video_tab, text="Video & Canvas")
        notebook.add(text_tab, text="Text Style")
        notebook.add(export_tab, text="Export")
        self._build_video_tab(self._wrap_tab_page(video_tab))
        self._build_text_tab(self._wrap_tab_page(text_tab))
        self._build_export_tab(self._wrap_tab_page(export_tab))

        self._build_preview_panel(right)
        self._build_description_section(description_section)
        self._build_upload_section(upload_section)
        self._show_section("video")

        self.preview_var = tk.StringVar(value="")

    def _show_section(self, section_id: str) -> None:
        if section_id not in self._section_frames:
            section_id = "video"
        self._active_section = section_id
        for frame in self._section_frames.values():
            frame.pack_forget()
        self._section_frames[section_id].pack(fill=tk.BOTH, expand=True)

        if section_id == "video":
            self.footer.pack(side=tk.BOTTOM, fill=tk.X)
        else:
            self.footer.pack_forget()

        for sid, btn in self._section_buttons.items():
            btn.configure(style="Accent.TButton" if sid == section_id else "TButton")

    def _build_description_section(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=2)
        parent.rowconfigure(0, weight=1)

        left = ttk.Frame(parent)
        left.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 10))
        left.columnconfigure(0, weight=1)

        api_box = ttk.LabelFrame(left, text="  GPT Setup  ", padding=10, style="Card.TLabelframe")
        api_box.grid(row=0, column=0, sticky=tk.EW, pady=(0, 10))
        api_box.columnconfigure(1, weight=1)
        self.openai_model_var = tk.StringVar(value="gpt-5.5")
        self.openai_api_key_var = tk.StringVar()
        ttk.Button(api_box, text="Set API Key", command=self.set_openai_api_key).grid(row=0, column=0, sticky=tk.W)
        ttk.Combobox(
            api_box,
            textvariable=self.openai_model_var,
            values=["gpt-5.5", "gpt-5.4", "gpt-4.1", "gpt-4o", "gpt-4o-mini"],
            state="readonly",
        ).grid(row=0, column=1, sticky=tk.EW, padx=(8, 0))

        prompt_box = ttk.LabelFrame(left, text="  Prompts  ", padding=10, style="Card.TLabelframe")
        prompt_box.grid(row=1, column=0, sticky=tk.EW)
        prompt_box.columnconfigure(0, weight=1)
        ttk.Label(prompt_box, text="System Prompt", style="CardMuted.TLabel").grid(row=0, column=0, sticky=tk.W)
        self.metadata_system_prompt_text = self._create_auto_text(prompt_box, height=5)
        self.metadata_system_prompt_text.grid(row=1, column=0, sticky=tk.EW, pady=(4, 10))
        ttk.Label(prompt_box, text="User Prompt", style="CardMuted.TLabel").grid(row=2, column=0, sticky=tk.W)
        self.metadata_user_prompt_text = self._create_auto_text(prompt_box, height=5)
        self.metadata_user_prompt_text.grid(row=3, column=0, sticky=tk.EW, pady=(4, 0))

        actions = ttk.Frame(left)
        actions.grid(row=2, column=0, sticky=tk.EW, pady=(10, 0))
        self.generate_metadata_btn = ttk.Button(actions, text="Generate Metadata", command=self.generate_metadata)
        self.generate_metadata_btn.pack(side=tk.LEFT)
        ttk.Button(actions, text="Save Metadata", command=self._save_current_editor_state).pack(side=tk.LEFT, padx=(8, 0))

        right = ttk.Frame(parent)
        right.grid(row=0, column=1, sticky=tk.NSEW)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        video_text_box = ttk.LabelFrame(right, text="  Video Top Text  ", padding=10, style="Card.TLabelframe")
        video_text_box.grid(row=0, column=0, sticky=tk.EW, pady=(0, 10))
        video_text_box.columnconfigure(0, weight=1)
        video_text_box.rowconfigure(0, weight=1)
        self.generated_video_text_text = self._create_auto_text(video_text_box, height=2)
        self.generated_video_text_text.grid(row=0, column=0, sticky=tk.NSEW, pady=2)
        ttk.Button(video_text_box, text="Update", command=self.apply_generated_video_text).grid(row=0, column=1, padx=(8, 0), sticky=tk.NSEW)

        title_box = ttk.LabelFrame(right, text="  Title  ", padding=10, style="Card.TLabelframe")
        title_box.grid(row=1, column=0, sticky=tk.EW, pady=(0, 10))
        self.ai_title_var = tk.StringVar()
        ttk.Entry(title_box, textvariable=self.ai_title_var).pack(fill=tk.X, ipady=4)

        desc_box = ttk.LabelFrame(right, text="  Description  ", padding=10, style="Card.TLabelframe")
        desc_box.grid(row=2, column=0, sticky=tk.NSEW, pady=(0, 10))
        self.ai_description_text = self._create_auto_text(desc_box, height=14)
        self.ai_description_text.pack(fill=tk.BOTH, expand=True)

        tags_box = ttk.LabelFrame(right, text="  Tags  ", padding=10, style="Card.TLabelframe")
        tags_box.grid(row=3, column=0, sticky=tk.EW)
        self.ai_tags_var = tk.StringVar()
        ttk.Entry(tags_box, textvariable=self.ai_tags_var).pack(fill=tk.X, ipady=4)

    def _build_upload_section(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)

        # 1. Video File Selector
        video_box = ttk.LabelFrame(parent, text="  Video File  ", padding=10, style="Card.TLabelframe")
        video_box.grid(row=0, column=0, sticky=tk.EW, pady=(0, 10))
        video_box.columnconfigure(0, weight=1)
        self.upload_video_var = tk.StringVar()
        ttk.Entry(video_box, textvariable=self.upload_video_var).grid(row=0, column=0, sticky=tk.EW, ipady=4)
        
        btn_frame = ttk.Frame(video_box)
        btn_frame.grid(row=0, column=1, padx=(8, 0))
        ttk.Button(btn_frame, text="Browse", command=self.browse_upload_video).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Fetch Video from Editor", command=self.fetch_video_and_metadata).pack(side=tk.LEFT, padx=(8, 0))

        # 2. Dedicated Metadata Fields
        metadata_box = ttk.LabelFrame(parent, text="  YouTube Metadata  ", padding=10, style="Card.TLabelframe")
        metadata_box.grid(row=1, column=0, sticky=tk.EW, pady=(0, 10))
        metadata_box.columnconfigure(0, weight=1)

        ttk.Label(metadata_box, text="Title", style="CardMuted.TLabel").grid(row=0, column=0, sticky=tk.W)
        self.upload_title_var = tk.StringVar()
        ttk.Entry(metadata_box, textvariable=self.upload_title_var).grid(row=1, column=0, sticky=tk.EW, ipady=4, pady=(2, 8))

        ttk.Label(metadata_box, text="Description", style="CardMuted.TLabel").grid(row=2, column=0, sticky=tk.W)
        self.upload_description_text = self._create_auto_text(metadata_box, height=6)
        self.upload_description_text.grid(row=3, column=0, sticky=tk.EW, pady=(2, 8))

        ttk.Label(metadata_box, text="Tags", style="CardMuted.TLabel").grid(row=4, column=0, sticky=tk.W)
        self.upload_tags_var = tk.StringVar()
        ttk.Entry(metadata_box, textvariable=self.upload_tags_var).grid(row=5, column=0, sticky=tk.EW, ipady=4, pady=(2, 0))

        # 3. Schedule Settings
        schedule_box = ttk.LabelFrame(parent, text="  Schedule  ", padding=10, style="Card.TLabelframe")
        schedule_box.grid(row=2, column=0, sticky=tk.EW, pady=(0, 10))
        schedule_box.columnconfigure(1, weight=1)
        
        self.upload_queue_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            schedule_box,
            text="Queue uploads (6-hour interval)",
            variable=self.upload_queue_var,
            command=self.refresh_upload_schedule_ui
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 8))

        self.upload_privacy_var = tk.StringVar(value="private")
        self.upload_date_var = tk.StringVar()
        self.upload_time_var = tk.StringVar()
        ttk.Label(schedule_box, text="Privacy", style="CardMuted.TLabel").grid(row=1, column=0, sticky=tk.W)
        ttk.Combobox(
            schedule_box,
            textvariable=self.upload_privacy_var,
            values=["private", "unlisted", "public"],
            state="readonly",
        ).grid(row=1, column=1, sticky=tk.EW, padx=(8, 0))
        ttk.Label(schedule_box, text="Date (YYYY-MM-DD)", style="CardMuted.TLabel").grid(row=2, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(schedule_box, textvariable=self.upload_date_var, state="readonly").grid(row=2, column=1, sticky=tk.EW, padx=(8, 0), pady=(8, 0))
        ttk.Label(schedule_box, text="Time (HH:MM)", style="CardMuted.TLabel").grid(row=3, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(schedule_box, textvariable=self.upload_time_var, state="readonly").grid(row=3, column=1, sticky=tk.EW, padx=(8, 0), pady=(8, 0))

        # 4. Connection & Upload History Box
        history_box = ttk.LabelFrame(parent, text="  Last Uploaded Video  ", padding=10, style="Card.TLabelframe")
        history_box.grid(row=3, column=0, sticky=tk.EW, pady=(0, 10))
        history_box.columnconfigure(0, weight=1)

        self.last_upload_title_lbl = ttk.Label(history_box, text="Title: None", font=("Segoe UI", 9, "bold"))
        self.last_upload_title_lbl.grid(row=0, column=0, sticky=tk.W)

        self.last_upload_time_lbl = ttk.Label(history_box, text="Scheduled/Uploaded: Never", style="CardMuted.TLabel")
        self.last_upload_time_lbl.grid(row=1, column=0, sticky=tk.W, pady=(4, 0))

        # 5. Actions Row
        actions = ttk.Frame(parent)
        actions.grid(row=4, column=0, sticky=tk.EW)
        
        # Connection Setup Frame (Slot 1, column 0)
        self.yt_setup_frame = ttk.Frame(actions)
        self.yt_setup_frame.grid(row=0, column=0, sticky=tk.W)
        
        self.connect_yt_btn = ttk.Button(self.yt_setup_frame, text="Connect YouTube", command=self.youtube_connect_start)
        self.connect_yt_btn.pack(side=tk.LEFT)

        # Small dropdown options button next to Connect YouTube button
        self.yt_menu = tk.Menu(self.connect_yt_btn, tearoff=False)
        self.yt_menu.add_command(label="Import client_secrets.json...", command=self.import_client_secrets)
        self.yt_menu.add_command(label="Disconnect / Sign Out", command=self.disconnect_youtube)
        
        self.yt_opt_btn = ttk.Menubutton(self.yt_setup_frame, text="▼")
        self.yt_opt_btn.pack(side=tk.LEFT, padx=(4, 0))
        self.yt_opt_btn["menu"] = self.yt_menu

        # Frame for active channel connection state (Slot 2, column 0 - overlaps Setup Frame)
        self.channel_status_frame = ttk.Frame(actions)
        self.channel_status_frame.grid(row=0, column=0, sticky=tk.W)
        
        self.channel_name_lbl = ttk.Label(self.channel_status_frame, text="Connected: Loading...", font=("Segoe UI", 9, "bold"))
        self.channel_name_lbl.pack(side=tk.LEFT)
        
        self.disconnect_link = ttk.Button(self.channel_status_frame, text="Disconnect", style="Toolbutton", command=self.disconnect_youtube)
        self.disconnect_link.pack(side=tk.LEFT, padx=(8, 0))

        # Upload / Schedule button (Slot 3, column 1)
        self.upload_btn = ttk.Button(actions, text="Upload / Schedule", style="Accent.TButton", command=self.youtube_upload_start)
        self.upload_btn.grid(row=0, column=1, padx=(8, 0), sticky=tk.W)

        # Check and set button visibility based on credentials files
        self.update_youtube_buttons_visibility()

    def fetch_video_and_metadata(self) -> None:
        self.start_export()
        
        # Populate dedicated fields from editor metadata
        title = self.ai_title_var.get().strip()
        description = self.ai_description_text.get("1.0", "end-1c").strip()
        tags = self.ai_tags_var.get().strip()
        
        self.upload_title_var.set(title)
        self.upload_description_text.delete("1.0", tk.END)
        self.upload_description_text.insert("1.0", description)
        self.upload_tags_var.set(tags)
        
        if HAS_GOOGLE_API:
            self.refresh_upload_schedule_ui()

    def calculate_next_upload_time(self) -> tuple[datetime, bool]:
        """Returns (target_time_utc, is_scheduled)."""
        now = datetime.now(timezone.utc)
        if not self.upload_queue_var.get():
            return now, False

        if not self.settings.last_upload_time:
            return now, False

        try:
            from datetime import timedelta
            last_time = datetime.fromisoformat(self.settings.last_upload_time.replace("Z", "+00:00"))
            if last_time + timedelta(hours=6) >= now:
                return last_time + timedelta(hours=6), True
        except Exception:
            pass
        return now, False

    def update_youtube_buttons_visibility(self) -> None:
        client_secrets_path = APP_DIR / "client_secrets.json"
        token_path = APP_DIR / "token.json"
        
        secrets_exist = client_secrets_path.exists()
        token_exists = token_path.exists()
        
        if secrets_exist and token_exists:
            # Hide setup buttons, show connection status
            self.yt_setup_frame.grid_remove()
            self.channel_status_frame.grid()
        else:
            # Hide connection status, show setup buttons
            self.channel_status_frame.grid_remove()
            self.yt_setup_frame.grid()

    def refresh_upload_schedule_ui(self) -> None:
        target_time, is_scheduled = self.calculate_next_upload_time()
        local_time = target_time.astimezone()
        self.upload_date_var.set(local_time.strftime("%Y-%m-%d"))
        self.upload_time_var.set(local_time.strftime("%H:%M"))

    def refresh_upload_history_ui(self) -> None:
        title = self.settings.last_upload_title or "None"
        self.last_upload_title_lbl.configure(text=f"Title: {title}")
        
        if self.settings.last_upload_time:
            try:
                last_time = datetime.fromisoformat(self.settings.last_upload_time.replace("Z", "+00:00"))
                local_time = last_time.astimezone()
                date_str = local_time.strftime("%Y-%m-%d")
                time_str = local_time.strftime("%I:%M %p")
                self.last_upload_time_lbl.configure(text=f"Scheduled/Uploaded: {date_str} at {time_str}")
            except Exception:
                self.last_upload_time_lbl.configure(text="Scheduled/Uploaded: Unknown format")
        else:
            self.last_upload_time_lbl.configure(text="Scheduled/Uploaded: Never")

    def browse_upload_video(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Exported Video",
            filetypes=[("MP4 Videos", "*.mp4"), ("All Files", "*.*")]
        )
        if path:
            self.upload_video_var.set(path)

    def youtube_connect_start(self) -> None:
        if not HAS_GOOGLE_API:
            messagebox.showerror(
                "Libraries Missing",
                "Google API libraries are not installed or failed to load.\n\n"
                "Please run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
            )
            return

        self.connect_yt_btn.configure(state=tk.DISABLED)
        self.set_status("Starting YouTube connection flow...")
        threading.Thread(target=self._run_youtube_connect, daemon=True).start()

    def _run_youtube_connect(self) -> None:
        try:
            client_secrets_path = APP_DIR / "client_secrets.json"
            token_path = APP_DIR / "token.json"

            if not client_secrets_path.exists() and not token_path.exists():
                raise FileNotFoundError(
                    f"Credentials file 'client_secrets.json' not found in:\n{APP_DIR}\n\n"
                    "Please download the OAuth Client ID json file from Google Cloud Console, "
                    "save it in that folder, and rename it to 'client_secrets.json'."
                )

            creds = None
            if token_path.exists():
                try:
                    creds = Credentials.from_authorized_user_file(str(token_path), ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"])
                except Exception:
                    pass

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    self.root.after(0, lambda: self.set_status("Refreshing expired credentials..."))
                    try:
                        creds.refresh(Request())
                    except Exception:
                        creds = None

                if not creds:
                    self.root.after(0, lambda: self.set_status("Please complete authentication in your web browser..."))
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(client_secrets_path),
                        scopes=["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]
                    )
                    
                    import webbrowser
                    original_open = webbrowser.open

                    def custom_open(url, new=0, autoraise=True):
                        # Copy URL to clipboard and show popup dialog safely from main thread
                        def copy_and_alert():
                            try:
                                self.root.clipboard_clear()
                                self.root.clipboard_append(url)
                                self.root.update()
                            except Exception:
                                pass
                            messagebox.showinfo(
                                "YouTube Authorization",
                                "The YouTube login link has been copied to your clipboard!\n\n"
                                "1. Open Google Chrome (where your channel is logged in).\n"
                                "2. Paste the link into the address bar (Ctrl+V) and press Enter.\n"
                                "3. Complete the login and grant permissions.\n"
                                "4. Return to this app once done."
                            )

                        self.root.after(0, copy_and_alert)

                        # Still attempt to open Chrome directly as a convenient shortcut
                        chrome_paths = [
                            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
                        ]
                        for path in chrome_paths:
                            if os.path.isfile(path):
                                try:
                                    subprocess.Popen([path, url])
                                    return True
                                except Exception:
                                    pass

                        for name in ("google-chrome", "chrome"):
                            try:
                                browser = webbrowser.get(name)
                                browser.open(url, new=new, autoraise=autoraise)
                                return True
                            except Exception:
                                continue

                        try:
                            original_open(url, new=new, autoraise=autoraise)
                        except Exception:
                            pass
                        return True

                    webbrowser.open = custom_open
                    try:
                        creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
                    finally:
                        webbrowser.open = original_open

                with open(token_path, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())

            self.root.after(0, lambda: self.set_status("Verifying connection with YouTube..."))
            youtube = build("youtube", "v3", credentials=creds)
            request = youtube.channels().list(
                part="snippet",
                mine=True
            )
            response = request.execute()

            channel_name = "Unknown Channel"
            if response.get("items"):
                channel_name = response["items"][0]["snippet"]["title"]

            self.root.after(0, lambda: self._youtube_connect_success(channel_name))
        except Exception as exc:
            self.root.after(0, lambda: self._youtube_connect_failed(str(exc)))

    def _youtube_connect_success(self, channel_name: str) -> None:
        self.connect_yt_btn.configure(state=tk.NORMAL)
        self.channel_name_lbl.configure(text=f"Connected: {channel_name}")
        self.set_status(f"Connected to YouTube channel: {channel_name}")
        self.update_youtube_buttons_visibility()
        messagebox.showinfo("YouTube Connected", f"Successfully connected to YouTube channel:\n{channel_name}")

    def _youtube_connect_failed(self, error_msg: str) -> None:
        self.connect_yt_btn.configure(state=tk.NORMAL)
        self.set_status("YouTube connection failed.", error=True)
        messagebox.showerror("YouTube Connection Error", error_msg)

    def import_client_secrets(self) -> None:
        path = filedialog.askopenfilename(
            title="Select client_secrets.json File",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")]
        )
        if not path:
            return

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            if "installed" not in data and "web" not in data:
                raise ValueError("Selected file does not appear to be a valid Google OAuth Client Secrets file.")

            dest_path = APP_DIR / "client_secrets.json"
            shutil.copy(path, dest_path)

            self.set_status("OAuth client secrets imported successfully.")
            self.update_youtube_buttons_visibility()
            messagebox.showinfo("Import Success", f"Successfully imported client secrets to:\n{dest_path}")
        except Exception as exc:
            messagebox.showerror("Import Error", f"Failed to import secrets: {exc}")

    def disconnect_youtube(self) -> None:
        token_path = APP_DIR / "token.json"
        if token_path.exists():
            try:
                os.remove(token_path)
            except Exception as exc:
                messagebox.showerror("Error", f"Failed to remove token file: {exc}")
                return

        self.connect_yt_btn.configure(text="Connect YouTube")
        self.set_status("YouTube channel disconnected.")
        self.update_youtube_buttons_visibility()
        messagebox.showinfo("Disconnected", "Successfully disconnected your YouTube channel.")

    def _start_time_update_loop(self) -> None:
        def update_loop():
            try:
                self.refresh_upload_schedule_ui()
            except Exception:
                pass
            self.root.after(5000, update_loop)
        update_loop()

    def _check_existing_youtube_auth(self) -> None:
        token_path = APP_DIR / "token.json"
        if token_path.exists():
            threading.Thread(target=self._query_channel_name_silent, daemon=True).start()
        self.refresh_upload_schedule_ui()
        self.update_youtube_buttons_visibility()
        self._start_time_update_loop()

    def _query_channel_name_silent(self) -> None:
        token_path = APP_DIR / "token.json"
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"])
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(token_path, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())

            youtube = build("youtube", "v3", credentials=creds)
            request = youtube.channels().list(
                part="snippet",
                mine=True
            )
            response = request.execute()
            if response.get("items"):
                channel_name = response["items"][0]["snippet"]["title"]
                self.root.after(0, lambda: self.connect_yt_btn.configure(text=f"Connected: {channel_name}"))
                self.root.after(0, self.update_youtube_buttons_visibility)
        except Exception:
            # Do NOT delete token.json automatically (e.g. if the user is simply offline during startup).
            # We still call update_youtube_buttons_visibility() to hide the connect buttons, assuming we are connected.
            self.root.after(0, self.update_youtube_buttons_visibility)

    def youtube_upload_start(self) -> None:
        if not HAS_GOOGLE_API:
            messagebox.showerror(
                "Libraries Missing",
                "Google API libraries are not installed or failed to load.\n\n"
                "Please run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
            )
            return

        video_path = self.upload_video_var.get().strip()
        if not video_path:
            messagebox.showerror("Upload Error", "Please select or export a video file first.")
            return
        if not Path(video_path).is_file():
            messagebox.showerror("Upload Error", f"Video file not found:\n{video_path}")
            return

        token_path = APP_DIR / "token.json"
        if not token_path.exists():
            messagebox.showerror("Upload Error", "You must connect to YouTube first. Click 'Connect YouTube'.")
            return

        title = self.upload_title_var.get().strip()
        if not title:
            messagebox.showerror("Upload Error", "Please enter a title for the video.")
            return

        self.current_upload_title = title

        # Auto schedule calculation:
        now = datetime.now(timezone.utc)
        target_time = now
        is_scheduled = False

        if self.upload_queue_var.get() and self.settings.last_upload_time:
            try:
                from datetime import timedelta
                last_time = datetime.fromisoformat(self.settings.last_upload_time.replace("Z", "+00:00"))
                if last_time + timedelta(hours=6) >= now:
                    target_time = last_time + timedelta(hours=6)
                    is_scheduled = True
            except Exception:
                pass

        target_time_str = target_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.settings.last_upload_time = target_time_str
        self._save_current_editor_state()

        # Instantly update UI fields with current local timezone representation
        self.refresh_upload_schedule_ui()

        if is_scheduled:
            schedule_param = target_time_str
        else:
            schedule_param = ""

        privacy = self.upload_privacy_var.get().strip() or "private"

        self.upload_btn.configure(state=tk.DISABLED)
        self.progress.grid()
        self.progress.configure(mode="determinate", value=0)
        self.set_status("Preparing video upload...")

        threading.Thread(
            target=self._run_youtube_upload,
            args=(video_path, title, privacy, schedule_param),
            daemon=True
        ).start()

    def _run_youtube_upload(self, video_path: str, title: str, privacy: str, schedule_utc_str: str) -> None:
        try:
            token_path = APP_DIR / "token.json"
            creds = Credentials.from_authorized_user_file(str(token_path), ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"])

            if creds and creds.expired and creds.refresh_token:
                self.root.after(0, lambda: self.set_status("Refreshing credentials..."))
                creds.refresh(Request())
                with open(token_path, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())

            youtube = build("youtube", "v3", credentials=creds)
            description = self.upload_description_text.get("1.0", "end-1c").strip()

            tags_raw = self.upload_tags_var.get().strip()
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

            body = {
                "snippet": {
                    "title": title,
                    "description": description,
                    "tags": tags,
                    "categoryId": "17",
                },
                "status": {
                    "privacyStatus": privacy
                }
            }

            if schedule_utc_str:
                body["status"]["publishAt"] = schedule_utc_str
                body["status"]["privacyStatus"] = "private"
                local_time = datetime.fromisoformat(schedule_utc_str.replace("Z", "+00:00")).astimezone()
                local_time_str = local_time.strftime("%Y-%m-%d %H:%M")
                self.root.after(0, lambda: self.set_status(f"Scheduling video for {local_time_str}..."))
            else:
                self.root.after(0, lambda: self.set_status("Uploading video to YouTube..."))

            media = MediaFileUpload(
                video_path,
                mimetype="video/mp4",
                chunksize=1024 * 1024,
                resumable=True
            )

            request = youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media
            )

            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    percent = int(status.progress() * 100)
                    self.root.after(0, lambda p=percent: self._upload_progress_update(p))

            video_id = response.get("id", "Unknown")
            self.root.after(0, lambda vid=video_id: self._youtube_upload_success(vid))

        except Exception as exc:
            self.root.after(0, lambda: self._youtube_upload_failed(str(exc)))

    def _upload_progress_update(self, percent: int) -> None:
        self.progress.configure(value=percent)
        self.set_status(f"Uploading video... {percent}% complete")

    def _youtube_upload_success(self, video_id: str) -> None:
        self.progress.stop()
        self.progress.grid_remove()
        self.upload_btn.configure(state=tk.NORMAL)
        self.set_status("Video uploaded successfully!")

        # Save last upload title persistently
        self.settings.last_upload_title = getattr(self, "current_upload_title", "")
        self._save_current_editor_state()
        self.refresh_upload_history_ui()

        url = f"https://youtu.be/{video_id}"
        msg = f"Video successfully uploaded to YouTube!\n\nVideo ID: {video_id}\nURL: {url}\n\nNote: If scheduled, it will become public at the specified time."
        messagebox.showinfo("Upload Success", msg)

    def _youtube_upload_failed(self, error_msg: str) -> None:
        self.progress.stop()
        self.progress.grid_remove()
        self.upload_btn.configure(state=tk.NORMAL)
        self.set_status("YouTube upload failed.", error=True)
        messagebox.showerror("YouTube Upload Error", error_msg)

    def _create_auto_text(self, parent: tk.Misc, *, height: int = 4) -> tk.Text:
        widget = tk.Text(
            parent,
            height=height,
            wrap=tk.WORD,
            font=("Segoe UI", 11),
            bg=THEME["surface2"],
            fg=THEME["text"],
            insertbackground=THEME["accent"],
            relief=tk.SOLID,
            bd=1,
            padx=8,
            pady=8,
            highlightthickness=0,
        )
        widget._min_height = height

        def resize(_event=None) -> None:
            try:
                line_count = int(widget.index("end-1c").split(".")[0])
            except (tk.TclError, ValueError):
                line_count = height
            widget.configure(height=max(widget._min_height, min(18, line_count + 1)))
            if not self._suspend_save:
                self._save_current_editor_state()

        widget.bind("<KeyRelease>", resize)
        widget.bind("<<Paste>>", lambda _event: self.root.after(1, resize))
        return widget

    def set_openai_api_key(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("OpenAI API Key")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        key_var = tk.StringVar(value=self.openai_api_key_var.get())
        ttk.Label(dialog, text="API key:").pack(anchor=tk.W, padx=12, pady=(12, 4))
        entry = ttk.Entry(dialog, textvariable=key_var, width=58, show="*")
        entry.pack(padx=12)
        entry.focus_set()

        def save_key() -> None:
            self.openai_api_key_var.set(key_var.get().strip())
            self._save_current_editor_state()
            dialog.destroy()

        ttk.Button(dialog, text="Save Key", command=save_key).pack(pady=12)

    def generate_metadata(self) -> None:
        if not self.openai_api_key_var.get().strip():
            messagebox.showerror("GPT Setup", "Set your OpenAI API key first.")
            return
        self._save_current_editor_state()
        self.generate_metadata_btn.configure(state=tk.DISABLED)
        self.set_status("Generating title, description, and tags with GPT...")
        threading.Thread(target=self._run_metadata_generation, daemon=True).start()

    def _run_metadata_generation(self) -> None:
        try:
            result = call_openai_metadata(
                api_key=self.openai_api_key_var.get().strip(),
                model=self.openai_model_var.get().strip() or "gpt-5.5",
                system_prompt=self.metadata_system_prompt_text.get("1.0", "end-1c").strip(),
                user_prompt=self.metadata_user_prompt_text.get("1.0", "end-1c").strip(),
            )
            self.root.after(0, lambda: self._metadata_generation_success(result))
        except Exception as exc:
            self.root.after(0, lambda: self._metadata_generation_failed(str(exc)))

    def _metadata_generation_success(self, raw_text: str) -> None:
        parsed = parse_metadata_response(raw_text)
        self.generated_video_text_text.delete("1.0", tk.END)
        self.generated_video_text_text.insert("1.0", normalize_video_text(parsed.get("video_text", "")))
        self.generated_video_text_text.event_generate("<KeyRelease>")
        self.ai_title_var.set(parsed.get("title", "").strip())
        self.ai_description_text.delete("1.0", tk.END)
        self.ai_description_text.insert("1.0", parsed.get("description", "").strip())
        self.ai_tags_var.set(parsed.get("tags", "").strip())
        self.generate_metadata_btn.configure(state=tk.NORMAL)
        self._save_current_editor_state()
        self.set_status("Metadata generated.")

    def _metadata_generation_failed(self, message: str) -> None:
        self.generate_metadata_btn.configure(state=tk.NORMAL)
        self.set_status(f"GPT generation failed: {message}", error=True)
        messagebox.showerror("GPT Error", message[:2000])

    def apply_generated_video_text(self) -> None:
        text = normalize_video_text(self.generated_video_text_text.get("1.0", "end-1c"))
        if not text:
            messagebox.showinfo("Video Text", "Generate or type video top text first.")
            return
        self._push_undo_immediate()
        widget = self._overlay_widgets.get("title")
        if widget is None:
            return
        self._suspend_save = True
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        title_overlay = self._overlay_from_settings("title")
        apply_color_to_range(widget, "1.0", "end-1c", title_overlay.font_color)
        first_end = widget.index("1.0 lineend")
        if widget.compare(first_end, ">", "1.0"):
            apply_color_to_range(widget, "1.0", first_end, title_overlay.first_line_color)
        self._suspend_save = False
        self._save_overlay_text_from_widget("title")
        self.generated_video_text_text.delete("1.0", tk.END)
        self.generated_video_text_text.insert("1.0", text)
        self.generated_video_text_text.event_generate("<KeyRelease>")
        self._finish_edit()
        self._render_preview()
        self.set_status("Video top text updated.")

    def _grid_field_box(
        self, parent: ttk.Frame, title: str, row: int, column: int, columnspan: int = 1
    ) -> ttk.LabelFrame:
        box = ttk.LabelFrame(parent, text=f"  {title}  ", padding=8, style="Sub.TLabelframe")
        box.grid(row=row, column=column, columnspan=columnspan, sticky=tk.NSEW, padx=4, pady=4)
        return box

    def open_trim_clips_dialog(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Trim Repeated Clips")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        content = ttk.Frame(dialog, padding=12)
        content.pack(fill=tk.BOTH, expand=True)
        for col in range(3):
            content.columnconfigure(col, weight=1)

        duration = self.preview_engine.duration_sec if self.preview_engine.is_loaded() else 0.0
        if duration <= 0 and self.video_path_var.get().strip():
            duration = get_video_duration(self.video_path_var.get().strip())

        ttk.Label(
            content,
            text=f"Source length: {format_time(duration)}. Set End to 0 to use the rest of the clip.",
            style="Muted.TLabel",
        ).grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 10))
        ttk.Label(content, text="Clip", style="Muted.TLabel").grid(row=1, column=0, sticky=tk.W)
        ttk.Label(content, text="Start (sec)", style="Muted.TLabel").grid(row=1, column=1, sticky=tk.W, padx=(8, 0))
        ttk.Label(content, text="End (sec)", style="Muted.TLabel").grid(row=1, column=2, sticky=tk.W, padx=(8, 0))

        clip1_start_var = tk.StringVar(value=self.clip1_trim_start_var.get())
        clip1_end_var = tk.StringVar(value=self.clip1_trim_end_var.get())
        clip2_start_var = tk.StringVar(value=self.clip2_trim_start_var.get())
        clip2_end_var = tk.StringVar(value=self.clip2_trim_end_var.get())
        fields = [
            ("Clip 1", clip1_start_var, clip1_end_var),
            ("Clip 2", clip2_start_var, clip2_end_var),
        ]
        entries: list[ttk.Entry] = []
        for index, (label, start_var, end_var) in enumerate(fields, start=2):
            ttk.Label(content, text=label).grid(row=index, column=0, sticky=tk.W, pady=(6, 0))
            start_entry = ttk.Entry(content, textvariable=start_var, width=12)
            start_entry.grid(row=index, column=1, sticky=tk.EW, padx=(8, 0), pady=(6, 0))
            end_entry = ttk.Entry(content, textvariable=end_var, width=12)
            end_entry.grid(row=index, column=2, sticky=tk.EW, padx=(8, 0), pady=(6, 0))
            entries.extend([start_entry, end_entry])

        actions = ttk.Frame(content)
        actions.grid(row=4, column=0, columnspan=3, sticky=tk.E, pady=(12, 0))

        def parse_seconds(value: str, label: str) -> float:
            try:
                number = float(value.strip() or "0")
            except ValueError as exc:
                raise ValueError(f"{label} must be a number.") from exc
            if number < 0:
                raise ValueError(f"{label} cannot be negative.")
            return number

        def save_trim() -> None:
            try:
                values = [
                    parse_seconds(clip1_start_var.get(), "Clip 1 start"),
                    parse_seconds(clip1_end_var.get(), "Clip 1 end"),
                    parse_seconds(clip2_start_var.get(), "Clip 2 start"),
                    parse_seconds(clip2_end_var.get(), "Clip 2 end"),
                ]
                for clip_idx, start, end in ((1, values[0], values[1]), (2, values[2], values[3])):
                    if end > 0 and end <= start:
                        raise ValueError(f"Clip {clip_idx} end must be after start, or set End to 0.")
                    if duration > 0 and start >= duration:
                        raise ValueError(f"Clip {clip_idx} start must be before the source ends.")
            except ValueError as exc:
                messagebox.showerror("Trim Clips", str(exc), parent=dialog)
                return

            self.clip1_trim_start_var.set(format_ffmpeg_seconds(values[0]))
            self.clip1_trim_end_var.set(format_ffmpeg_seconds(values[1]))
            self.clip2_trim_start_var.set(format_ffmpeg_seconds(values[2]))
            self.clip2_trim_end_var.set(format_ffmpeg_seconds(values[3]))
            self._update_trim_summary()
            self._save_current_editor_state()
            dialog.destroy()

        ttk.Button(actions, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(actions, text="Save Trim", command=save_trim, style="Accent.TButton").pack(side=tk.RIGHT, padx=(0, 8))
        if entries:
            entries[0].focus_set()

    def _update_trim_summary(self) -> None:
        if not hasattr(self, "trim_summary_var"):
            return

        def parse(value: str) -> float:
            try:
                return max(0.0, float(value.strip() or "0"))
            except (TypeError, ValueError):
                return 0.0

        def label(start_value: str, end_value: str) -> str:
            start = parse(start_value)
            end = parse(end_value)
            if start <= 0.0 and end <= 0.0:
                return "full"
            if end <= 0.0:
                return f"{format_ffmpeg_seconds(start)}s to end"
            return f"{format_ffmpeg_seconds(start)}s to {format_ffmpeg_seconds(end)}s"

        self.trim_summary_var.set(
            "Clip 1: "
            + label(self.clip1_trim_start_var.get(), self.clip1_trim_end_var.get())
            + " | Clip 2: "
            + label(self.clip2_trim_start_var.get(), self.clip2_trim_end_var.get())
        )

    def _active_text_widget(self) -> scrolledtext.ScrolledText:
        return self._overlay_widgets[self._active_overlay_id]

    def _overlay_label_map(self) -> dict[str, str]:
        labels: dict[str, str] = {"title": "Title Text", "footer": "Footer Text"}
        for item in self.settings.text_overlays:
            oid = item.get("id")
            if oid:
                labels[oid] = item.get("label", oid)
        return labels

    def _overlay_from_settings(self, overlay_id: str) -> TextOverlay:
        for item in self.settings.text_overlays:
            if item.get("id") == overlay_id:
                return overlay_from_dict(item)
        defaults = {o.id: o for o in default_text_overlays()}
        return defaults.get(overlay_id, default_title_overlay())

    def _update_overlay_in_settings(self, overlay: TextOverlay) -> None:
        payload = overlay_to_dict(overlay)
        updated = False
        for index, item in enumerate(self.settings.text_overlays):
            if item.get("id") == overlay.id:
                self.settings.text_overlays[index] = payload
                updated = True
                break
        if not updated:
            self.settings.text_overlays.append(payload)

    def _save_overlay_text_from_widget(self, overlay_id: str) -> None:
        widget = self._overlay_widgets.get(overlay_id)
        if widget is None:
            return
        overlay = self._overlay_from_settings(overlay_id)
        overlay.text = widget.get("1.0", tk.END).strip()
        overlay.text_spans = [
            {"text": span.text, "color": span.color}
            for span in extract_text_spans(widget, overlay.font_color)
        ]
        self._update_overlay_in_settings(overlay)

    def _save_active_overlay_properties(self) -> None:
        if self._suspend_overlay_switch or self._suspend_save:
            return
        overlay = self._overlay_from_settings(self._active_overlay_id)
        self._save_overlay_text_from_widget(self._active_overlay_id)
        overlay = self._overlay_from_settings(self._active_overlay_id)

        def parse_int(value: str, default: int = 0) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        overlay.text_case = self.text_case_var.get() or "none"
        overlay.first_line_color = self.first_line_color_var.get().strip() or "#FFD700"
        overlay.text_position = self.text_position_var.get() or "top"
        overlay.text_custom_x = parse_int(self.text_custom_x_var.get(), 0)
        overlay.text_custom_y = parse_int(self.text_custom_y_var.get(), 120)
        overlay.font_size = parse_int(self.font_size_var.get(), 72)
        overlay.first_line_font_size = parse_int(
            self.first_line_font_size_var.get(),
            max(overlay.font_size + 16, int(overlay.font_size * 1.25)),
        )
        overlay.font_color = self.font_color_var.get().strip() or "#FFFFFF"
        overlay.font_path = self.font_path_var.get().strip() or DEFAULT_FONT
        overlay.text_box_enabled = bool(self.text_box_var.get())
        overlay.text_box_color = self.text_box_color_var.get().strip() or "#000000"
        overlay.text_shadow_enabled = bool(self.text_shadow_var.get())
        overlay.text_outline_enabled = bool(self.text_outline_var.get())
        overlay.outline_color = self.outline_color_var.get().strip() or "#000000"
        overlay.outline_size = parse_int(self.outline_size_var.get(), 4)
        self._update_overlay_in_settings(overlay)

    def _apply_overlay_text_to_widget(self, overlay: TextOverlay, widget: scrolledtext.ScrolledText) -> None:
        spans = spans_from_overlay(overlay)
        if spans:
            apply_spans_to_widget(widget, spans, overlay.font_color)
            return
        widget.delete("1.0", tk.END)
        widget.insert("1.0", overlay.text)
        if overlay.text.strip():
            apply_color_to_range(widget, "1.0", "end-1c", overlay.font_color)
            first_end = widget.index("1.0 lineend")
            if widget.compare(first_end, ">", "1.0"):
                apply_color_to_range(widget, "1.0", first_end, overlay.first_line_color)

    def _apply_overlay_properties_to_ui(self, overlay: TextOverlay) -> None:
        self.text_case_var.set(overlay.text_case or "none")
        self.first_line_color_var.set(overlay.first_line_color or "#FFD700")
        self.text_position_var.set(overlay.text_position or "top")
        self.text_custom_x_var.set(str(overlay.text_custom_x))
        self.text_custom_y_var.set(str(overlay.text_custom_y))
        self.font_size_var.set(str(overlay.font_size))
        self.first_line_font_size_var.set(str(overlay.first_line_font_size))
        self.font_color_var.set(overlay.font_color)
        self.font_path_var.set(overlay.font_path)
        self.text_box_var.set(overlay.text_box_enabled)
        self.text_box_color_var.set(overlay.text_box_color)
        self.text_shadow_var.set(overlay.text_shadow_enabled)
        self.text_outline_var.set(overlay.text_outline_enabled)
        self.outline_color_var.set(overlay.outline_color)
        self.outline_size_var.set(str(overlay.outline_size))

    def _refresh_overlay_selector(self) -> None:
        labels = self._overlay_label_map()
        self._overlay_combo_to_id = {label: oid for oid, label in labels.items()}
        self._overlay_id_to_combo = {oid: label for oid, label in labels.items()}
        self.active_overlay_combo.configure(values=list(self._overlay_combo_to_id.keys()))
        if self._active_overlay_id not in labels:
            self._active_overlay_id = "title"
        self.active_overlay_var.set(self._overlay_id_to_combo.get(self._active_overlay_id, "Title Text"))

    def _refresh_overlay_highlights(self) -> None:
        for overlay_id, frame in self._overlay_frames.items():
            color = THEME["accent"] if overlay_id == self._active_overlay_id else THEME["border"]
            frame.configure(bg=color)

    def _select_overlay(self, overlay_id: str) -> None:
        if overlay_id == self._active_overlay_id or self._suspend_overlay_switch:
            return
        self._save_active_overlay_properties()
        self._active_overlay_id = overlay_id
        self.settings.active_text_overlay_id = overlay_id
        self._suspend_overlay_switch = True
        self._apply_overlay_properties_to_ui(self._overlay_from_settings(overlay_id))
        self.active_overlay_var.set(self._overlay_id_to_combo.get(overlay_id, overlay_id))
        if hasattr(self, "editing_layer_var"):
            self.editing_layer_var.set(self._overlay_id_to_combo.get(overlay_id, overlay_id))
        self._refresh_overlay_highlights()
        self._suspend_overlay_switch = False

    def _on_overlay_combo_selected(self, _event=None) -> None:
        overlay_id = self._overlay_combo_to_id.get(self.active_overlay_var.get(), "title")
        self._select_overlay(overlay_id)

    def _on_overlay_focus(self, overlay_id: str) -> None:
        self._select_overlay(overlay_id)

    def _on_overlay_text_changed(self, overlay_id: str, _event=None) -> None:
        if self._suspend_save:
            return
        if overlay_id != self._active_overlay_id:
            self._select_overlay(overlay_id)
        widget = self._overlay_widgets[overlay_id]
        default = self._overlay_from_settings(overlay_id).font_color
        content = widget.get("1.0", "end-1c")
        if content:
            for i in range(len(content)):
                idx = widget.index(f"1.0 + {i} chars")
                has_color = any(tag.startswith("c_") for tag in widget.tag_names(idx))
                if not has_color:
                    end = widget.index(f"1.0 + {i + 1} chars")
                    apply_color_to_range(widget, idx, end, default)
        self._on_settings_changed()

    def _create_overlay_text_box(self, parent: ttk.Frame, overlay_id: str, column: int) -> None:
        labels = {"title": "Title Text", "footer": "Footer Text"}
        frame = tk.LabelFrame(
            parent,
            text=f"  {labels.get(overlay_id, overlay_id)}  ",
            bg=THEME["border"],
            fg=THEME["accent"],
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief=tk.SOLID,
            highlightthickness=0,
            labelanchor="nw",
            padx=2,
            pady=2,
        )
        frame.grid(row=0, column=column, sticky=tk.NSEW, padx=(0 if column == 0 else 4, 0))
        self._overlay_frames[overlay_id] = frame

        inner = tk.Frame(frame, bg=THEME["surface2"])
        inner.pack(fill=tk.BOTH, expand=True)
        widget = scrolledtext.ScrolledText(
            inner,
            height=3 if overlay_id == "footer" else 4,
            wrap=tk.WORD,
            font=("Segoe UI", 11),
            bg=THEME["surface2"],
            fg=THEME["text"],
            insertbackground=THEME["accent"],
            selectbackground=THEME["accent"],
            selectforeground="#ffffff",
            relief=tk.SOLID,
            bd=1,
            padx=8,
            pady=6,
            highlightthickness=0,
        )
        widget.pack(fill=tk.BOTH, expand=True)
        widget.bind("<FocusIn>", lambda _e, oid=overlay_id: self._on_overlay_focus(oid))
        widget.bind("<Button-1>", lambda _e, oid=overlay_id: self._on_overlay_focus(oid))
        widget.bind("<KeyRelease>", lambda e, oid=overlay_id: self._on_overlay_text_changed(oid, e))
        widget.bind("<<Paste>>", lambda e, oid=overlay_id: self._on_overlay_text_changed(oid, e))
        self._overlay_widgets[overlay_id] = widget

    def _build_text_format_toolbar(self, parent: ttk.Frame) -> None:
        self.text_case_var = tk.StringVar(value="none")
        btn_row = ttk.Frame(parent, style="Card.TFrame")
        btn_row.pack(fill=tk.X)

        format_buttons = [
            ("AA", "uppercase", "UPPERCASE"),
            ("aa", "lowercase", "lowercase"),
            ("Aa", "title", "Title Case"),
            ("Ab", "sentence", "Sentence"),
            ("Abc", "none", "Normal"),
        ]
        for col, (label, case, tooltip) in enumerate(format_buttons):
            btn = ttk.Button(
                btn_row,
                text=label,
                width=3,
                style="Format.TButton",
                command=lambda c=case: self._set_text_case(c),
            )
            btn.grid(row=0, column=col, padx=(0 if col == 0 else 2, 0), sticky=tk.EW)
            btn_row.columnconfigure(col, weight=1)
            self._create_tooltip(btn, tooltip)

        case_row = ttk.Frame(parent, style="Card.TFrame")
        case_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(case_row, text="Preset", style="CardMuted.TLabel").pack(side=tk.LEFT)
        ttk.Combobox(
            case_row,
            textvariable=self.text_case_var,
            values=list(TEXT_CASE_OPTIONS.keys()),
            state="readonly",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))

    def _build_text_color_toolbar(self, parent: ttk.Frame) -> None:
        color_buttons = [
            ("Default Color", self.choose_default_text_color, "Set color for new text or current selection"),
            ("Selection Color", self.choose_selection_color, "Color highlighted text (even one character)"),
            ("Line 1 Color", self.choose_first_line_color, "Color the first row of text"),
        ]
        for idx, (label, command, tip) in enumerate(color_buttons):
            btn = ttk.Button(parent, text=label, style="Format.TButton", command=command)
            btn.pack(fill=tk.X, pady=(0 if idx == 0 else 4, 0))
            self._create_tooltip(btn, tip)

    def _create_tooltip(self, widget: tk.Misc, text: str) -> None:
        tip = tk.Toplevel(widget)
        tip.withdraw()
        tip.overrideredirect(True)
        tip.configure(bg=THEME["surface2"])
        label = tk.Label(
            tip, text=text, bg=THEME["surface2"], fg=THEME["text"], font=("Segoe UI", 9), padx=8, pady=4
        )
        label.pack()

        def show(_event) -> None:
            x = widget.winfo_rootx() + 10
            y = widget.winfo_rooty() + widget.winfo_height() + 4
            tip.geometry(f"+{x}+{y}")
            tip.deiconify()

        def hide(_event) -> None:
            tip.withdraw()

        widget.bind("<Enter>", show)
        widget.bind("<Leave>", hide)

    def _set_text_case(self, case: str) -> None:
        self._push_undo_immediate()
        self.text_case_var.set(case)
        widget = self._active_text_widget()
        spans = extract_text_spans(widget, self.font_color_var.get())
        if spans and case != "none":
            formatted_spans = [TextSpan(apply_text_case(span.text, case), span.color) for span in spans]
            self._suspend_save = True
            apply_spans_to_widget(widget, formatted_spans, self.font_color_var.get())
            self._suspend_save = False
        self._finish_edit()

    def _ask_color(self, title: str, initial: str) -> str | None:
        _, color = colorchooser.askcolor(color=initial or "#FFFFFF", title=title)
        if color:
            return normalize_hex_color(color)
        return None

    def choose_default_text_color(self) -> None:
        self._push_undo_immediate()
        color = self._ask_color("Default Text Color", self.font_color_var.get())
        if not color:
            return
        self.font_color_var.set(color)
        widget = self._active_text_widget()
        try:
            start = widget.index(tk.SEL_FIRST)
            end = widget.index(tk.SEL_LAST)
            self._suspend_save = True
            apply_color_to_range(widget, start, end, color)
            self._suspend_save = False
        except tk.TclError:
            pass
        self._finish_edit()

    def choose_selection_color(self) -> None:
        widget = self._active_text_widget()
        try:
            widget.index(tk.SEL_FIRST)
        except tk.TclError:
            messagebox.showinfo("Select Text", "Highlight text in the box first - even a single character works.")
            return
        self._push_undo_immediate()
        color = self._ask_color("Selection Color", self.selection_color_var.get())
        if not color:
            return
        self.selection_color_var.set(color)
        start = widget.index(tk.SEL_FIRST)
        end = widget.index(tk.SEL_LAST)
        self._suspend_save = True
        apply_color_to_range(widget, start, end, color)
        self._suspend_save = False
        self._finish_edit()

    def choose_first_line_color(self) -> None:
        widget = self._active_text_widget()
        content = widget.get("1.0", "end-1c")
        if not content:
            messagebox.showinfo("No Text", "Type text first, then choose a first-line color.")
            return
        self._push_undo_immediate()
        color = self._ask_color("First Line Color", self.first_line_color_var.get())
        if not color:
            return
        self.first_line_color_var.set(color)
        end = widget.index("1.0 lineend")
        self._suspend_save = True
        apply_color_to_range(widget, "1.0", end, color)
        self._suspend_save = False
        self._finish_edit()

    def _push_undo_immediate(self) -> None:
        if self._suspend_undo:
            return
        self._push_undo_state(asdict(self.settings))

    def _schedule_undo_push(self) -> None:
        if self._suspend_undo:
            return
        if self._undo_pending_snapshot is None:
            self._undo_pending_snapshot = asdict(self.settings)
        if self._undo_push_after is not None:
            self.root.after_cancel(self._undo_push_after)
        self._undo_push_after = self.root.after(500, self._commit_undo_push)

    def _commit_undo_push(self) -> None:
        if self._undo_pending_snapshot is not None:
            self._push_undo_state(self._undo_pending_snapshot)
            self._undo_pending_snapshot = None
        self._undo_push_after = None

    def _push_undo_state(self, snapshot: dict) -> None:
        if self._undo_stack and snapshot == self._undo_stack[-1]:
            return
        self._undo_stack.append(snapshot)
        while len(self._undo_stack) > UNDO_LIMIT:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _restore_snapshot(self, snapshot: dict) -> None:
        self._suspend_undo = True
        self._suspend_save = True
        base = asdict(default_settings())
        base.update(snapshot)
        self.settings = EditorSettings(**{k: base[k] for k in asdict(EditorSettings()).keys()})
        self._apply_settings_to_ui()
        self._suspend_undo = False
        self._suspend_save = False
        self.settings_manager.save(self.settings)
        self._update_preview_summary()
        self._schedule_preview_render()

    def undo_action(self) -> None:
        if not self._undo_stack:
            self.set_status("Nothing to undo.")
            return
        self._commit_undo_push()
        current = asdict(self._collect_settings_from_ui())
        self._redo_stack.append(current)
        while len(self._redo_stack) > UNDO_LIMIT:
            self._redo_stack.pop(0)
        previous = self._undo_stack.pop()
        self._restore_snapshot(previous)
        self.set_status("Undo.")

    def redo_action(self) -> None:
        if not self._redo_stack:
            self.set_status("Nothing to redo.")
            return
        current = asdict(self._collect_settings_from_ui())
        self._push_undo_state(current)
        nxt = self._redo_stack.pop()
        self._restore_snapshot(nxt)
        self.set_status("Redo.")

    def _finish_edit(self) -> None:
        self._suspend_undo = True
        self._on_settings_changed()
        self._suspend_undo = False

    def _ensure_default_text_colors(self) -> None:
        widget = self._active_text_widget()
        content = widget.get("1.0", "end-1c")
        if not content:
            return
        default = self.font_color_var.get()
        for i in range(len(content)):
            idx = widget.index(f"1.0 + {i} chars")
            has_color = any(tag.startswith("c_") for tag in widget.tag_names(idx))
            if not has_color:
                end = widget.index(f"1.0 + {i + 1} chars")
                apply_color_to_range(widget, idx, end, default)

    def _build_preview_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="  Live Preview  ", padding=8, style="Card.TLabelframe")
        panel.pack(fill=tk.BOTH, expand=True)

        self.preview_wrap = tk.Frame(
            panel,
            bg=THEME["preview_bg"],
            highlightthickness=1,
            highlightbackground=THEME["border"],
            width=self.preview_display_w,
            height=self.preview_display_h,
        )
        self.preview_wrap.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(0, 6))
        self.preview_wrap.pack_propagate(False)
        self.preview_wrap.bind("<Configure>", self._on_preview_wrap_configure)
        self.preview_canvas = tk.Canvas(
            self.preview_wrap,
            width=self.preview_display_w,
            height=self.preview_display_h,
            bg=THEME["preview_bg"],
            highlightthickness=0,
        )
        self.preview_canvas.pack(expand=True, padx=2, pady=2, anchor=tk.CENTER)
        self._draw_preview_placeholder()

        bottom = ttk.Frame(panel, style="Card.TFrame")
        bottom.pack(side=tk.BOTTOM, fill=tk.X)
        bottom.columnconfigure(0, weight=3)
        bottom.columnconfigure(1, weight=2)

        self.preview_var_detail = tk.StringVar(value="")

        timeline_box = ttk.LabelFrame(bottom, text="  Timeline  ", padding=3, style="Sub.TLabelframe")
        timeline_box.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 3))

        timeline_times_row = ttk.Frame(timeline_box, style="Card.TFrame")
        timeline_times_row.pack(fill=tk.X, pady=(0, 2))
        self.timeline_start_var = tk.StringVar(value="0:00")
        self.timeline_end_var = tk.StringVar(value="0:00")
        ttk.Label(timeline_times_row, textvariable=self.timeline_start_var, style="Card.TLabel", width=6).pack(
            side=tk.LEFT
        )
        ttk.Label(timeline_times_row, textvariable=self.timeline_end_var, style="Card.TLabel", width=6).pack(
            side=tk.RIGHT
        )

        timeline_wrap = tk.Frame(
            timeline_box,
            bg=THEME["border"],
            highlightthickness=1,
            highlightbackground=THEME["accent"],
            highlightcolor=THEME["accent"],
        )
        timeline_wrap.pack(fill=tk.X)
        self.timeline_canvas = tk.Canvas(
            timeline_wrap,
            height=34,
            bg=THEME["surface2"],
            highlightthickness=0,
            cursor="hand2",
        )
        self.timeline_canvas.pack(fill=tk.X, padx=1, pady=1)
        self.timeline_canvas.bind("<Configure>", lambda _e: self._draw_timeline())
        self.timeline_canvas.bind("<Button-1>", self._on_timeline_press)
        self.timeline_canvas.bind("<B1-Motion>", self._on_timeline_drag)
        self.timeline_canvas.bind("<ButtonRelease-1>", self._on_timeline_release)

        self.timeline_var = tk.DoubleVar(value=0.0)
        self._timeline_dragging = False
        self._sound_marker_dragging = False
        self._timeline_thumb_x = 0
        self._sound_marker_x = -1

        controls_row = ttk.Frame(bottom, style="Card.TFrame")
        controls_row.grid(row=0, column=1, sticky=tk.NSEW, padx=(3, 0))
        controls_row.columnconfigure(0, weight=2)
        controls_row.columnconfigure(1, weight=3)

        zoom_box = ttk.LabelFrame(controls_row, text="  Zoom  ", padding=3, style="Sub.TLabelframe")
        zoom_box.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 3))
        zoom_row = ttk.Frame(zoom_box, style="Card.TFrame")
        zoom_row.pack(fill=tk.X)
        ttk.Button(zoom_row, text="-", width=3, command=lambda: self._nudge_zoom(-0.05)).pack(side=tk.LEFT)
        self.zoom_var = tk.DoubleVar(value=1.0)
        self.zoom_slider = tk.Scale(
            zoom_row,
            from_=ZOOM_MIN,
            to=ZOOM_MAX,
            resolution=0.01,
            orient=tk.HORIZONTAL,
            variable=self.zoom_var,
            showvalue=0,
            command=self._on_zoom_slider_changed,
            length=80,
            bg=THEME["surface"],
            fg=THEME["text"],
            troughcolor=THEME["surface2"],
            activebackground=THEME["accent"],
            highlightthickness=0,
            sliderrelief=tk.FLAT,
            borderwidth=0,
        )
        self.zoom_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self.zoom_slider.bind("<ButtonPress-1>", self._on_zoom_drag_start)
        ttk.Button(zoom_row, text="+", width=3, command=lambda: self._nudge_zoom(0.05)).pack(side=tk.LEFT)
        self.zoom_label_var = tk.StringVar(value="1.00x")
        ttk.Label(zoom_box, textvariable=self.zoom_label_var, style="Card.TLabel").pack(anchor=tk.E, pady=(2, 0))

        playback_box = ttk.LabelFrame(controls_row, text="  Playback  ", padding=3, style="Sub.TLabelframe")
        playback_box.grid(row=0, column=1, sticky=tk.NSEW, padx=(3, 0))
        play_row = ttk.Frame(playback_box, style="Card.TFrame")
        play_row.pack(fill=tk.X)
        self.play_btn = ttk.Button(play_row, text="Play", command=self.toggle_play)
        self.play_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(play_row, text="Stop", command=self.stop_playback).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        self.time_var = tk.StringVar(value="00:00 / 00:00")
        ttk.Label(playback_box, textvariable=self.time_var, style="Card.TLabel").pack(anchor=tk.CENTER, pady=(2, 0))

    def _preview_size_for_area(self, width: int, height: int) -> tuple[int, int]:
        available_w = max(1, width - 8)
        available_h = max(1, height - 8)
        aspect = CANVAS_WIDTH / CANVAS_HEIGHT
        display_w = max(1, min(available_w, int(available_h * aspect)))
        display_h = max(1, int(display_w / aspect))
        return display_w, display_h

    def _draw_preview_placeholder(self) -> None:
        self.preview_canvas.delete("all")
        self.preview_canvas.create_text(
            self.preview_display_w // 2,
            self.preview_display_h // 2,
            text="Select a video",
            fill=THEME["text_muted"],
            font=("Segoe UI", max(9, min(14, self.preview_display_w // 22))),
            justify=tk.CENTER,
            tags="placeholder",
        )

    def _on_preview_wrap_configure(self, event) -> None:
        display_w, display_h = self._preview_size_for_area(event.width, event.height)
        if display_w == self.preview_display_w and display_h == self.preview_display_h:
            return
        self.preview_display_w = display_w
        self.preview_display_h = display_h
        self.preview_canvas.configure(width=display_w, height=display_h)

        if self._preview_resize_after_id is not None:
            self.root.after_cancel(self._preview_resize_after_id)
        self._preview_resize_after_id = self.root.after(80, self._finish_preview_resize)

    def _finish_preview_resize(self) -> None:
        self._preview_resize_after_id = None
        if self.preview_engine.is_loaded():
            self._render_preview()
        else:
            self._draw_preview_placeholder()

    def _build_video_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        row = 0

        self.bg_color_var = tk.StringVar()
        bg_box = self._grid_field_box(parent, "Background", row, 0)
        ttk.Button(bg_box, text="Background Color", command=self.pick_bg_color).pack(fill=tk.X)

        self.video_position_var = tk.StringVar()
        pos_box = self._grid_field_box(parent, "Video Position", row, 1)
        ttk.Combobox(
            pos_box,
            textvariable=self.video_position_var,
            values=["center", "top", "bottom", "custom"],
            state="readonly",
        ).pack(fill=tk.X)
        row += 1

        self.video_custom_x_var = tk.StringVar()
        x_box = self._grid_field_box(parent, "Video X", row, 0)
        ttk.Entry(x_box, textvariable=self.video_custom_x_var).pack(fill=tk.X)

        self.video_custom_y_var = tk.StringVar()
        y_box = self._grid_field_box(parent, "Video Y Offset", row, 1)
        ttk.Entry(y_box, textvariable=self.video_custom_y_var).pack(fill=tk.X)
        row += 1

        self.video_scale_var = tk.StringVar()
        scale_box = self._grid_field_box(parent, "Scale / Zoom", row, 0)
        ttk.Entry(scale_box, textvariable=self.video_scale_var).pack(fill=tk.X)

        self.video_center_align_var = tk.BooleanVar(value=True)
        align_box = self._grid_field_box(parent, "Center Align", row, 1)
        ttk.Checkbutton(
            align_box,
            text="Lock elements to horizontal center",
            variable=self.video_center_align_var,
        ).pack(anchor=tk.W)
        row += 1

        self.crop_mode_var = tk.BooleanVar()
        crop_box = self._grid_field_box(parent, "Crop Mode", row, 0, columnspan=2)
        ttk.Checkbutton(
            crop_box,
            text="Fill frame (may cut edges)",
            variable=self.crop_mode_var,
        ).pack(anchor=tk.W)
        row += 1

        ttk.Label(
            parent,
            text=f"Output canvas is fixed at {CANVAS_WIDTH}×{CANVAS_HEIGHT}. "
            "Fit mode keeps the full video visible with padding.",
            style="CardMuted.TLabel",
            wraplength=420,
        ).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=4, pady=(6, 0))

    def _build_text_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        row = 0

        layer_hint = self._grid_field_box(parent, "Active Layer", row, 0, columnspan=2)
        self.editing_layer_var = tk.StringVar(value="Title Text")
        ttk.Label(
            layer_hint,
            textvariable=self.editing_layer_var,
            style="Card.TLabel",
            wraplength=360,
        ).pack(anchor=tk.W)
        ttk.Label(
            layer_hint,
            text="Properties below apply to the selected text box above.",
            style="CardMuted.TLabel",
            wraplength=360,
        ).pack(anchor=tk.W, pady=(4, 0))
        row += 1

        case_box = self._grid_field_box(parent, "Text Case", row, 0)
        ttk.Combobox(
            case_box,
            textvariable=self.text_case_var,
            values=list(TEXT_CASE_OPTIONS.keys()),
            state="readonly",
        ).pack(fill=tk.X)

        self.text_position_var = tk.StringVar()
        pos_box = self._grid_field_box(parent, "Text Position", row, 1)
        ttk.Combobox(
            pos_box,
            textvariable=self.text_position_var,
            values=["top", "center", "bottom", "custom"],
            state="readonly",
        ).pack(fill=tk.X)
        row += 1

        self.text_custom_x_var = tk.StringVar()
        self.text_custom_y_var = tk.StringVar()

        self.font_size_var = tk.StringVar()
        size_box = self._grid_field_box(parent, "Font Size", row, 0)
        ttk.Entry(size_box, textvariable=self.font_size_var).pack(fill=tk.X)

        self.first_line_font_size_var = tk.StringVar()
        line1_size_box = self._grid_field_box(parent, "Line 1 Size", row, 1)
        ttk.Entry(line1_size_box, textvariable=self.first_line_font_size_var).pack(fill=tk.X)
        row += 1

        self.text_outline_var = tk.BooleanVar()
        self.outline_color_var = tk.StringVar()
        self.outline_size_var = tk.StringVar()
        border_box = self._grid_field_box(parent, "Text Border", row, 0, columnspan=2)
        ttk.Checkbutton(border_box, text="Enable border", variable=self.text_outline_var).pack(anchor=tk.W)
        ttk.Button(border_box, text="Border Color", command=self.pick_border_color).pack(fill=tk.X, pady=(4, 0))
        border_size_row = ttk.Frame(border_box, style="Card.TFrame")
        border_size_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(border_size_row, text="Size", style="CardMuted.TLabel").pack(side=tk.LEFT)
        ttk.Entry(border_size_row, textvariable=self.outline_size_var, width=6).pack(side=tk.LEFT, padx=(6, 0))
        row += 1

        self.font_path_var = tk.StringVar()
        font_box = self._grid_field_box(parent, "Font File", row, 0, columnspan=2)
        font_path_row = ttk.Frame(font_box, style="Card.TFrame")
        font_path_row.pack(fill=tk.X)
        font_path_row.columnconfigure(0, weight=1)
        ttk.Entry(font_path_row, textvariable=self.font_path_var).grid(row=0, column=0, sticky=tk.EW)
        ttk.Button(font_path_row, text="Browse", command=self.select_font).grid(row=0, column=1, padx=(6, 0))
        row += 1

        self.text_box_var = tk.BooleanVar()
        self.text_box_color_var = tk.StringVar()
        tbox_box = self._grid_field_box(parent, "Background Box", row, 0)
        ttk.Checkbutton(tbox_box, text="Enable text box", variable=self.text_box_var).pack(anchor=tk.W)

        self.text_shadow_var = tk.BooleanVar()
        shadow_box = self._grid_field_box(parent, "Shadow", row, 1)
        ttk.Checkbutton(shadow_box, text="Enable shadow", variable=self.text_shadow_var).pack(anchor=tk.W)

    def _build_export_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        row = 0

        self.output_folder_var = tk.StringVar()
        folder_box = self._grid_field_box(parent, "Output Folder", row, 0, columnspan=2)
        folder_row = ttk.Frame(folder_box, style="Card.TFrame")
        folder_row.pack(fill=tk.X)
        folder_row.columnconfigure(0, weight=1)
        ttk.Entry(folder_row, textvariable=self.output_folder_var).grid(row=0, column=0, sticky=tk.EW)
        ttk.Button(folder_row, text="Browse", command=self.select_output_folder).grid(row=0, column=1, padx=(6, 0))
        row += 1

        self.output_filename_var = tk.StringVar()
        name_box = self._grid_field_box(parent, "File Name", row, 0)
        ttk.Entry(name_box, textvariable=self.output_filename_var).pack(fill=tk.X)

        self.export_quality_var = tk.StringVar()
        quality_box = self._grid_field_box(parent, "Export Quality", row, 1)
        ttk.Combobox(
            quality_box,
            textvariable=self.export_quality_var,
            values=list(QUALITY_PRESETS.keys()),
            state="readonly",
        ).pack(fill=tk.X)
        row += 1

        format_box = self._grid_field_box(parent, "Format", row, 0, columnspan=2)
        ttk.Label(format_box, text="MP4 (H.264 + AAC)", style="CardMuted.TLabel").pack(anchor=tk.W)
        row += 1

        self.end_sound_enabled_var = tk.BooleanVar(value=False)
        self.end_sound_path_var = tk.StringVar(value=DEFAULT_CLAP_SOUND)
        self.end_sound_start_var = tk.StringVar(value="5")
        sound_box = self._grid_field_box(parent, "End Sound", row, 0, columnspan=2)
        ttk.Checkbutton(
            sound_box,
            text="Play sound effect in the last seconds",
            variable=self.end_sound_enabled_var,
        ).pack(anchor=tk.W)
        sound_row = ttk.Frame(sound_box, style="Card.TFrame")
        sound_row.pack(fill=tk.X, pady=(6, 0))
        sound_row.columnconfigure(0, weight=1)
        ttk.Entry(sound_row, textvariable=self.end_sound_path_var).grid(row=0, column=0, sticky=tk.EW)
        ttk.Button(sound_row, text="Browse", command=self.select_end_sound).grid(row=0, column=1, padx=(6, 0))
        timing_row = ttk.Frame(sound_box, style="Card.TFrame")
        timing_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(timing_row, text="Start before end (sec)", style="CardMuted.TLabel").pack(side=tk.LEFT)
        ttk.Entry(timing_row, textvariable=self.end_sound_start_var, width=8).pack(side=tk.LEFT, padx=(8, 0))
        row += 1

        export_action_box = self._grid_field_box(parent, "Export", row, 0, columnspan=2)
        ttk.Button(
            export_action_box,
            text="Export Video",
            command=self.start_export,
            style="Accent.TButton",
        ).pack(fill=tk.X, ipady=6)

    def _bind_events(self) -> None:
        tracked_vars = [
            self.video_path_var,
            self.bg_color_var,
            self.video_position_var,
            self.video_custom_x_var,
            self.video_custom_y_var,
            self.video_scale_var,
            self.text_position_var,
            self.font_size_var,
            self.first_line_font_size_var,
            self.font_color_var,
            self.font_path_var,
            self.text_box_color_var,
            self.outline_color_var,
            self.outline_size_var,
            self.output_folder_var,
            self.output_filename_var,
            self.export_quality_var,
            self.end_sound_path_var,
            self.end_sound_start_var,
            self.clip1_trim_start_var,
            self.clip1_trim_end_var,
            self.clip2_trim_start_var,
            self.clip2_trim_end_var,
            self.openai_model_var,
            self.ai_title_var,
            self.ai_tags_var,
        ]
        for var in tracked_vars:
            var.trace_add("write", lambda *_: self._on_settings_changed())
        for var in (
            self.crop_mode_var,
            self.video_center_align_var,
            self.end_sound_enabled_var,
            self.repeat_clip_twice_var,
            self.text_box_var,
            self.text_shadow_var,
            self.text_outline_var,
        ):
            var.trace_add("write", lambda *_: self._on_settings_changed())
        self.text_case_var.trace_add("write", lambda *_: self._on_settings_changed())
        for var in (self.selection_color_var, self.first_line_color_var):
            var.trace_add("write", lambda *_: self._on_settings_changed())
        self.root.bind("<Control-z>", lambda _e: self.undo_action())
        self.root.bind("<Control-y>", lambda _e: self.redo_action())
        self.root.bind("<Control-Y>", lambda _e: self.redo_action())
        self.root.bind("<Control-Shift-z>", lambda _e: self.redo_action())
        self.root.bind("<Control-Shift-Z>", lambda _e: self.redo_action())
        self.preview_canvas.bind("<MouseWheel>", self._on_preview_wheel)
        self.preview_canvas.bind("<Button-1>", self._on_preview_press)
        self.preview_canvas.bind("<B1-Motion>", self._on_preview_drag)
        self.preview_canvas.bind("<ButtonRelease-1>", self._on_preview_release)
        self.preview_canvas.bind("<Leave>", self._on_preview_release)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _apply_settings_to_ui(self) -> None:
        self._suspend_save = True
        self._suspend_zoom_sync = True
        self._suspend_overlay_switch = True
        s = self.settings
        if not s.text_overlays:
            migrated = migrate_settings_dict(asdict(s))
            s.text_overlays = migrated.get("text_overlays", [])
        self.video_path_var.set(s.video_path)
        for overlay in get_text_overlays(s):
            widget = self._overlay_widgets.get(overlay.id)
            if widget is not None:
                self._apply_overlay_text_to_widget(overlay, widget)
        self._active_overlay_id = s.active_text_overlay_id or "title"
        if self._active_overlay_id not in self._overlay_widgets:
            self._active_overlay_id = "title"
        self._refresh_overlay_selector()
        self._apply_overlay_properties_to_ui(self._overlay_from_settings(self._active_overlay_id))
        self._refresh_overlay_highlights()
        self.bg_color_var.set(s.background_color)
        self.video_position_var.set(s.video_position)
        self.video_custom_x_var.set(str(s.video_custom_x))
        self.video_custom_y_var.set(str(s.video_custom_y))
        self.video_scale_var.set(str(s.video_scale))
        self.video_center_align_var.set(s.video_center_align)
        self.crop_mode_var.set(s.crop_mode)
        self.output_folder_var.set(s.output_folder)
        self.output_filename_var.set(s.output_filename)
        self.export_quality_var.set(s.export_quality)
        self.end_sound_enabled_var.set(s.end_sound_enabled)
        self.end_sound_path_var.set(s.end_sound_path)
        self.end_sound_start_var.set(str(s.end_sound_start_before_end))
        self.repeat_clip_twice_var.set(s.repeat_clip_twice)
        self.clip1_trim_start_var.set(str(s.clip1_trim_start))
        self.clip1_trim_end_var.set(str(s.clip1_trim_end))
        self.clip2_trim_start_var.set(str(s.clip2_trim_start))
        self.clip2_trim_end_var.set(str(s.clip2_trim_end))
        self._update_trim_summary()
        self.openai_api_key_var.set(s.openai_api_key)
        self.openai_model_var.set(s.openai_model)
        self.metadata_system_prompt_text.delete("1.0", tk.END)
        self.metadata_system_prompt_text.insert("1.0", s.metadata_system_prompt)
        self.metadata_user_prompt_text.delete("1.0", tk.END)
        self.metadata_user_prompt_text.insert("1.0", s.metadata_user_prompt)
        self.generated_video_text_text.delete("1.0", tk.END)
        self.generated_video_text_text.insert("1.0", s.generated_video_text)
        self.generated_video_text_text.event_generate("<KeyRelease>")
        self.ai_title_var.set(s.generated_title)
        self.ai_description_text.delete("1.0", tk.END)
        self.ai_description_text.insert("1.0", s.generated_description)
        self.ai_tags_var.set(s.generated_tags)
        self.upload_title_var.set(s.upload_title)
        self.upload_description_text.delete("1.0", tk.END)
        self.upload_description_text.insert("1.0", s.upload_description)
        self.upload_tags_var.set(s.upload_tags)
        self.upload_queue_var.set(s.upload_queue)
        if HAS_GOOGLE_API:
            self.refresh_upload_schedule_ui()
            self.refresh_upload_history_ui()
        self._sync_zoom_slider(s.video_scale)
        self._suspend_zoom_sync = False
        self._suspend_overlay_switch = False
        self._suspend_save = False
        self._update_preview_summary()
        self._schedule_preview_render()

    def _sync_zoom_slider(self, scale: float) -> None:
        scale = max(ZOOM_MIN, min(scale, ZOOM_MAX))
        self.zoom_var.set(scale)
        self.zoom_label_var.set(f"{scale:.2f}x")

    def _collect_settings_from_ui(self) -> EditorSettings:
        def parse_int(value: str, default: int = 0) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        def parse_float(value: str, default: float = 1.0) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        self._save_active_overlay_properties()
        for overlay_id in self._overlay_widgets:
            if overlay_id != self._active_overlay_id:
                self._save_overlay_text_from_widget(overlay_id)

        overlays = [overlay_to_dict(self._overlay_from_settings(oid)) for oid in self._overlay_widgets]
        title = self._overlay_from_settings("title")

        return EditorSettings(
            video_path=self.video_path_var.get().strip(),
            text=title.text,
            text_case=title.text_case,
            text_spans=title.text_spans,
            first_line_color=title.first_line_color,
            background_color=self.bg_color_var.get().strip() or "#000000",
            video_position=self.video_position_var.get() or "center",
            video_custom_x=parse_int(self.video_custom_x_var.get(), 0),
            video_custom_y=parse_int(self.video_custom_y_var.get(), 0),
            video_scale=parse_float(self.video_scale_var.get(), 1.0),
            video_center_align=bool(self.video_center_align_var.get()),
            crop_mode=bool(self.crop_mode_var.get()),
            text_position=title.text_position,
            text_custom_x=title.text_custom_x,
            text_custom_y=title.text_custom_y,
            font_size=title.font_size,
            first_line_font_size=title.first_line_font_size,
            font_color=title.font_color,
            font_path=title.font_path,
            text_box_enabled=title.text_box_enabled,
            text_box_color=title.text_box_color,
            text_shadow_enabled=title.text_shadow_enabled,
            text_outline_enabled=title.text_outline_enabled,
            outline_color=title.outline_color,
            outline_size=title.outline_size,
            text_overlays=overlays,
            active_text_overlay_id=self._active_overlay_id,
            output_folder=self.output_folder_var.get().strip() or str(OUTPUT_DIR),
            output_filename=self.output_filename_var.get().strip() or "shorts_output",
            export_quality=self.export_quality_var.get() or "balanced",
            end_sound_enabled=bool(self.end_sound_enabled_var.get()),
            end_sound_path=self.end_sound_path_var.get().strip() or DEFAULT_CLAP_SOUND,
            end_sound_start_before_end=parse_float(self.end_sound_start_var.get(), 5.0),
            repeat_clip_twice=bool(self.repeat_clip_twice_var.get()),
            clip1_trim_start=parse_float(self.clip1_trim_start_var.get(), 0.0),
            clip1_trim_end=parse_float(self.clip1_trim_end_var.get(), 0.0),
            clip2_trim_start=parse_float(self.clip2_trim_start_var.get(), 0.0),
            clip2_trim_end=parse_float(self.clip2_trim_end_var.get(), 0.0),
            openai_api_key=self.openai_api_key_var.get().strip(),
            openai_model=self.openai_model_var.get().strip() or "gpt-5.5",
            metadata_system_prompt=self.metadata_system_prompt_text.get("1.0", "end-1c").strip(),
            metadata_user_prompt=self.metadata_user_prompt_text.get("1.0", "end-1c").strip(),
            generated_video_text=normalize_video_text(self.generated_video_text_text.get("1.0", "end-1c")),
            generated_title=self.ai_title_var.get().strip(),
            generated_description=self.ai_description_text.get("1.0", "end-1c").strip(),
            generated_tags=self.ai_tags_var.get().strip(),
            last_preset=self.settings.last_preset,
            last_upload_time=self.settings.last_upload_time,
            upload_title=self.upload_title_var.get().strip(),
            upload_description=self.upload_description_text.get("1.0", "end-1c").strip(),
            upload_tags=self.upload_tags_var.get().strip(),
            upload_queue=bool(self.upload_queue_var.get()),
            last_upload_title=self.settings.last_upload_title,
            export_counts=getattr(self.settings, "export_counts", {}),
        )

    def _save_current_editor_state(self) -> None:
        if self._suspend_save:
            return
        self.settings = self._collect_settings_from_ui()
        self.settings_manager.save(self.settings)

    def _on_text_changed(self, _event=None) -> None:
        if self._suspend_save:
            return
        self._ensure_default_text_colors()
        self._on_settings_changed()

    def _on_settings_changed(self) -> None:
        if self._suspend_save:
            return
        if not self._suspend_undo:
            self._schedule_undo_push()
        if not self._suspend_overlay_switch:
            self._save_active_overlay_properties()
        self.settings = self._collect_settings_from_ui()
        if not self._suspend_zoom_sync:
            self._sync_zoom_slider(self.settings.video_scale)
        self._update_preview_summary()
        self._save_current_editor_state()
        self._schedule_preview_render()
        if hasattr(self, "timeline_canvas"):
            self._draw_timeline()

    def _update_preview_summary(self) -> None:
        s = self.settings
        quality_label = QUALITY_PRESETS.get(s.export_quality, QUALITY_PRESETS["balanced"])["label"]
        active = self._overlay_from_settings(self._active_overlay_id)
        layer_count = len(get_text_overlays(s))
        self.set_status(
            f"Editing {active.label} | {layer_count} text layers | Export: {s.output_filename}.mp4 ({quality_label})"
        )

    def _schedule_preview_render(self) -> None:
        if self._preview_after_id is not None:
            self.root.after_cancel(self._preview_after_id)
        self._preview_after_id = self.root.after(40, self._render_preview)

    def _render_preview(self, frame: np.ndarray | None = None) -> None:
        self._preview_after_id = None
        if not self.preview_engine.is_loaded():
            self._draw_preview_placeholder()
            return
        if frame is None:
            frame = self.preview_engine.seek(self.preview_engine.current_frame_idx)
        if frame is None:
            return
        settings = self._collect_settings_from_ui()
        result = PreviewCompositor.compose(frame, settings)
        self._compose_layout = result
        display_size = (max(1, self.preview_display_w), max(1, self.preview_display_h))
        display = result.image.resize(display_size, Image.Resampling.LANCZOS)
        self._preview_photo = ImageTk.PhotoImage(display)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(
            0,
            0,
            image=self._preview_photo,
            anchor=tk.NW,
            tags="preview_image",
        )
        self._draw_drag_overlays()
        self._update_time_display()
        self._draw_timeline()
        self.preview_canvas.update_idletasks()

    def _canvas_to_preview(self, cx: int, cy: int) -> tuple[int, int]:
        px = int(cx / CANVAS_WIDTH * self.preview_display_w)
        py = int(cy / CANVAS_HEIGHT * self.preview_display_h)
        return px, py

    def _preview_to_canvas(self, px: int, py: int) -> tuple[int, int]:
        display_w = max(1, self.preview_display_w)
        display_h = max(1, self.preview_display_h)
        cx = int(px / display_w * CANVAS_WIDTH)
        cy = int(py / display_h * CANVAS_HEIGHT)
        return cx, cy

    def _text_resize_handle_rect(self, rect: ElementRect) -> ElementRect:
        size = TEXT_RESIZE_HANDLE
        return ElementRect(rect.x + rect.w - size, rect.y + rect.h - size, size, size)

    def _clamp_video_layer_position(self, value: int, layer_size: int, canvas_size: int) -> int:
        visible_grip = 32
        min_value = min(0, -layer_size + visible_grip)
        max_value = max(canvas_size - visible_grip, canvas_size - layer_size)
        return max(min_value, min(value, max_value))

    def _centered_text_x(self, rect: ElementRect, overlay: TextOverlay) -> int:
        box_pad = 16 if overlay.text_box_enabled else 0
        text_w = max(1, rect.w - box_pad * 2)
        return (CANVAS_WIDTH - text_w) // 2

    def _draw_drag_overlays(self) -> None:
        if not self._compose_layout:
            return
        if self._compose_layout.video_rect:
            rect = self._compose_layout.video_rect
            x1, y1 = self._canvas_to_preview(rect.x, rect.y)
            x2, y2 = self._canvas_to_preview(rect.x + rect.w, rect.y + rect.h)
            color = THEME["video_outline"]
            self.preview_canvas.create_rectangle(
                x1, y1, x2, y2, outline=color, width=2, dash=(5, 3), tags="overlay"
            )

        for entry in self._compose_layout.text_rects:
            rect = entry.rect
            color = THEME["accent"] if entry.overlay_id == self._active_overlay_id else THEME["text_outline"]
            x1, y1 = self._canvas_to_preview(rect.x, rect.y)
            x2, y2 = self._canvas_to_preview(rect.x + rect.w, rect.y + rect.h)
            self.preview_canvas.create_rectangle(
                x1, y1, x2, y2, outline=color, width=2, dash=(5, 3), tags="overlay"
            )
            handle = self._text_resize_handle_rect(rect)
            hx1, hy1 = self._canvas_to_preview(handle.x, handle.y)
            hx2, hy2 = self._canvas_to_preview(handle.x + handle.w, handle.y + handle.h)
            handle_fill = THEME["success"] if entry.overlay_id == self._active_overlay_id else THEME["accent"]
            self.preview_canvas.create_rectangle(
                hx1,
                hy1,
                hx2,
                hy2,
                fill=handle_fill,
                outline=THEME["text"],
                width=1,
                tags="overlay",
            )

    def _hit_test_preview(self, cx: int, cy: int) -> str | None:
        if not self._compose_layout:
            return None
        for entry in reversed(self._compose_layout.text_rects):
            handle = self._text_resize_handle_rect(entry.rect)
            if handle.x <= cx <= handle.x + handle.w and handle.y <= cy <= handle.y + handle.h:
                return f"resize:{entry.overlay_id}"
        for entry in reversed(self._compose_layout.text_rects):
            r = entry.rect
            if r.x <= cx <= r.x + r.w and r.y <= cy <= r.y + r.h:
                return f"text:{entry.overlay_id}"
        if self._compose_layout.video_rect:
            r = self._compose_layout.video_rect
            if r.x <= cx <= r.x + r.w and r.y <= cy <= r.y + r.h:
                return "video"
        return None

    def _on_preview_press(self, event) -> None:
        if not self.preview_engine.is_loaded():
            return
        cx, cy = self._preview_to_canvas(event.x, event.y)
        target = self._hit_test_preview(cx, cy)
        if not target:
            return
        self.stop_playback()
        self._push_undo_immediate()
        self._drag_target = target
        self._drag_start_canvas_x = cx
        self._drag_start_canvas_y = cy
        settings = self._collect_settings_from_ui()
        self._drag_origin_x = settings.video_custom_x
        self._drag_origin_y = settings.video_custom_y
        if target == "video" and self._compose_layout and self._compose_layout.video_layout:
            layout = self._compose_layout.video_layout
            if settings.crop_mode:
                self._drag_origin_x = layout.crop_x
                self._drag_origin_y = layout.crop_y
            else:
                self._drag_origin_x = layout.pad_x
                self._drag_origin_y = layout.pad_y
        if target.startswith("resize:") and self._compose_layout:
            overlay_id = target.split(":", 1)[1]
            self._select_overlay(overlay_id)
            self._drag_overlay_id = overlay_id
            overlay = self._overlay_from_settings(overlay_id)
            text_rect = next(
                (entry.rect for entry in self._compose_layout.text_rects if entry.overlay_id == overlay_id),
                None,
            )
            if text_rect is not None:
                box_pad = 16 if overlay.text_box_enabled else 0
                self.text_position_var.set("custom")
                self.text_custom_x_var.set(str(text_rect.x + box_pad))
                self.text_custom_y_var.set(str(text_rect.y + box_pad))
                self._drag_origin_font_size = overlay.font_size
                self._drag_origin_rect_h = max(20, text_rect.h)
            self.preview_canvas.configure(cursor="size_nw_se")
        elif target.startswith("text:") and self._compose_layout:
            overlay_id = target.split(":", 1)[1]
            self._select_overlay(overlay_id)
            self._drag_overlay_id = overlay_id
            overlay = self._overlay_from_settings(overlay_id)
            text_rect = next(
                (entry.rect for entry in self._compose_layout.text_rects if entry.overlay_id == overlay_id),
                None,
            )
            if text_rect is not None:
                self._drag_origin_x = overlay.text_custom_x
                self._drag_origin_y = overlay.text_custom_y
                self._drag_offset_x = cx - text_rect.x
                self._drag_offset_y = cy - text_rect.y
            self.preview_canvas.configure(cursor="fleur")

    def _on_preview_drag(self, event) -> None:
        if not self._drag_target or not self._compose_layout:
            return
        cx, cy = self._preview_to_canvas(event.x, event.y)
        self._suspend_save = True
        if self._drag_target == "video" and self._compose_layout.video_layout:
            layout = self._compose_layout.video_layout
            dx = cx - self._drag_start_canvas_x
            dy = cy - self._drag_start_canvas_y
            self.video_position_var.set("custom")
            if bool(self.crop_mode_var.get()):
                max_crop_x = max(0, layout.fit_w - layout.output_w)
                max_crop_y = max(0, layout.fit_h - layout.output_h)
                if bool(self.video_center_align_var.get()):
                    new_x = max_crop_x // 2
                else:
                    new_x = max(0, min(self._drag_origin_x - dx, max_crop_x))
                new_y = max(0, min(self._drag_origin_y - dy, max_crop_y))
            else:
                new_x = (
                    (CANVAS_WIDTH - layout.fit_w) // 2
                    if bool(self.video_center_align_var.get())
                    else self._clamp_video_layer_position(self._drag_origin_x + dx, layout.fit_w, CANVAS_WIDTH)
                )
                new_y = self._clamp_video_layer_position(self._drag_origin_y + dy, layout.fit_h, CANVAS_HEIGHT)
            self.video_custom_x_var.set(str(int(new_x)))
            self.video_custom_y_var.set(str(int(new_y)))
        elif self._drag_target.startswith("resize:") and self._compose_layout:
            dy = cy - self._drag_start_canvas_y
            scale = max(0.35, (self._drag_origin_rect_h + dy) / self._drag_origin_rect_h)
            new_size = int(self._drag_origin_font_size * scale)
            new_size = max(FONT_SIZE_MIN, min(FONT_SIZE_MAX, new_size))
            self.font_size_var.set(str(new_size))
        elif self._drag_target.startswith("text:") and self._compose_layout:
            overlay_id = self._drag_target.split(":", 1)[1]
            overlay = self._overlay_from_settings(overlay_id)
            text_rect = next(
                (entry.rect for entry in self._compose_layout.text_rects if entry.overlay_id == overlay_id),
                None,
            )
            if text_rect is not None:
                if bool(self.video_center_align_var.get()):
                    new_x = self._centered_text_x(text_rect, overlay)
                else:
                    new_x = cx - self._drag_offset_x
                new_y = cy - self._drag_offset_y
                new_x = max(0, min(new_x, CANVAS_WIDTH - text_rect.w))
                new_y = max(0, min(new_y, CANVAS_HEIGHT - text_rect.h))
                self.text_position_var.set("custom")
                self.text_custom_x_var.set(str(int(new_x)))
                self.text_custom_y_var.set(str(int(new_y)))
        self._suspend_save = False
        self.settings = self._collect_settings_from_ui()
        self._render_preview()

    def _on_preview_release(self, _event=None) -> None:
        if self._drag_target:
            self._finish_edit()
        self._drag_target = None
        self._drag_overlay_id = None
        self.preview_canvas.configure(cursor="")

    def _on_zoom_drag_start(self, _event=None) -> None:
        self._push_undo_immediate()

    def _on_zoom_slider_changed(self, _value: str) -> None:
        if self._suspend_zoom_sync:
            return
        scale = max(ZOOM_MIN, min(float(self.zoom_var.get()), ZOOM_MAX))
        self._suspend_save = True
        self.video_scale_var.set(f"{scale:.2f}")
        self._suspend_save = False
        self.zoom_label_var.set(f"{scale:.2f}x")
        self._save_current_editor_state()
        self._update_preview_summary()
        self._render_preview()

    def _update_time_display(self) -> None:
        current = self.preview_engine.current_time()
        total = self.preview_engine.duration_sec
        self.time_var.set(f"{format_time(current)} / {format_time(total)}")
        self.timeline_start_var.set("0:00")
        self.timeline_end_var.set(format_timeline_time(total))

    def _timeline_track_metrics(self) -> tuple[int, int, int, int]:
        canvas = self.timeline_canvas
        width = max(canvas.winfo_width(), 10)
        height = max(canvas.winfo_height(), 10)
        track_h = 8
        track_y = height - track_h - 6
        usable = max(1, width - TIMELINE_THUMB_WIDTH)
        return width, track_y, track_h, usable

    def _timeline_progress(self) -> float:
        if self.preview_engine.frame_count <= 1:
            return 0.0
        return self.preview_engine.current_frame_idx / (self.preview_engine.frame_count - 1)

    def _timeline_thumb_position(self, progress: float | None = None) -> int:
        _, _, _, usable = self._timeline_track_metrics()
        if progress is None:
            progress = self._timeline_progress()
        return int(max(0.0, min(1.0, progress)) * usable)

    def _draw_timeline(self) -> None:
        canvas = self.timeline_canvas
        canvas.delete("all")
        width, track_y, track_h, usable = self._timeline_track_metrics()
        height = max(canvas.winfo_height(), 10)

        canvas.create_rectangle(0, track_y, width, track_y + track_h, fill=THEME["border"], outline=THEME["border"])
        progress = self._timeline_progress()
        px = self._timeline_thumb_position(progress)
        if self.preview_engine.frame_count > 0:
            canvas.create_rectangle(0, track_y, px + TIMELINE_THUMB_WIDTH // 2, track_y + track_h, fill=THEME["accent"], outline="")

        self._sound_marker_x = -1
        if self.preview_engine.duration_sec > 0 and bool(self.end_sound_enabled_var.get()):
            try:
                before_end = max(0.0, float(self.end_sound_start_var.get()))
            except (TypeError, ValueError):
                before_end = 5.0
            start_sec = max(0.0, self.preview_engine.duration_sec - before_end)
            marker_fraction = start_sec / self.preview_engine.duration_sec
            marker_x = int(max(0.0, min(1.0, marker_fraction)) * width)
            self._sound_marker_x = marker_x
            marker_w = 12
            marker_top = 2
            marker_bottom = height - 2
            canvas.create_rectangle(
                marker_x - marker_w // 2,
                marker_top,
                marker_x + marker_w // 2,
                marker_bottom,
                fill=THEME["success"],
                outline=THEME["text"],
                width=1,
                tags="sound_marker",
            )
            canvas.create_text(
                marker_x,
                marker_top + 9,
                text="CLAP",
                fill="#08110c",
                font=("Segoe UI", 7, "bold"),
                tags="sound_marker",
            )

        thumb_x = px
        thumb_y = max(2, track_y - TIMELINE_THUMB_HEIGHT - 2)
        self._timeline_thumb_x = thumb_x
        canvas.create_rectangle(
            thumb_x,
            thumb_y,
            thumb_x + TIMELINE_THUMB_WIDTH,
            thumb_y + TIMELINE_THUMB_HEIGHT,
            fill=THEME["accent"],
            outline=THEME["text"],
            width=1,
            tags="thumb",
        )
        canvas.create_line(
            thumb_x + TIMELINE_THUMB_WIDTH // 2,
            thumb_y + TIMELINE_THUMB_HEIGHT,
            thumb_x + TIMELINE_THUMB_WIDTH // 2,
            track_y,
            fill=THEME["success"],
            width=2,
            tags="thumb",
        )

    def _timeline_fraction_from_x(self, x: float) -> float:
        width = max(self.timeline_canvas.winfo_width(), 1)
        return max(0.0, min(1.0, float(x) / width))

    def _seek_to_fraction(self, fraction: float) -> None:
        if not self.preview_engine.is_loaded() or self.preview_engine.frame_count <= 0:
            return
        max_idx = max(0, self.preview_engine.frame_count - 1)
        frame_idx = int(round(fraction * max_idx))
        self.preview_engine.seek(frame_idx)
        self.timeline_var.set(frame_idx)
        self._update_time_display()
        self._draw_timeline()
        self._schedule_preview_render()

    def _timeline_x_to_fraction(self, x: float) -> float:
        canvas_x = x - self.timeline_canvas.winfo_rootx()
        return self._timeline_fraction_from_x(canvas_x)

    def _is_on_sound_marker(self, x: float) -> bool:
        return self._sound_marker_x >= 0 and abs(x - self._sound_marker_x) <= 12

    def _set_end_sound_from_timeline_x(self, x: float) -> None:
        if self.preview_engine.duration_sec <= 0:
            return
        fraction = self._timeline_fraction_from_x(x)
        start_sec = fraction * self.preview_engine.duration_sec
        before_end = max(0.0, self.preview_engine.duration_sec - start_sec)
        self.end_sound_start_var.set(f"{before_end:.2f}".rstrip("0").rstrip("."))
        self._save_current_editor_state()
        self._draw_timeline()

    def _on_timeline_press(self, event) -> None:
        if not self.preview_engine.is_loaded():
            return
        if bool(self.end_sound_enabled_var.get()) and self._is_on_sound_marker(event.x):
            self._sound_marker_dragging = True
            self.stop_playback()
            self._set_end_sound_from_timeline_x(event.x)
            self.root.bind("<B1-Motion>", self._on_timeline_global_drag)
            self.root.bind("<ButtonRelease-1>", self._on_timeline_global_release)
            return
        self._scrubbing = True
        self._timeline_dragging = True
        self.stop_playback()
        self._seek_to_fraction(self._timeline_fraction_from_x(event.x))
        self.root.bind("<B1-Motion>", self._on_timeline_global_drag)
        self.root.bind("<ButtonRelease-1>", self._on_timeline_global_release)

    def _on_timeline_drag(self, event) -> None:
        if self._sound_marker_dragging:
            self._set_end_sound_from_timeline_x(event.x)
            return
        if not self._timeline_dragging:
            return
        self._seek_to_fraction(self._timeline_fraction_from_x(event.x))

    def _on_timeline_global_drag(self, event) -> None:
        if self._sound_marker_dragging:
            canvas_x = event.x_root - self.timeline_canvas.winfo_rootx()
            self._set_end_sound_from_timeline_x(canvas_x)
            return
        if not self._timeline_dragging:
            return
        self._seek_to_fraction(self._timeline_x_to_fraction(event.x_root))

    def _end_timeline_scrub(self) -> None:
        self._timeline_dragging = False
        self._sound_marker_dragging = False
        self._scrubbing = False
        for sequence in ("<B1-Motion>", "<ButtonRelease-1>"):
            try:
                self.root.unbind(sequence)
            except tk.TclError:
                pass

    def _on_timeline_release(self, _event=None) -> None:
        self._end_timeline_scrub()

    def _on_timeline_global_release(self, _event=None) -> None:
        self._end_timeline_scrub()

    def _nudge_zoom(self, delta: float) -> None:
        self._push_undo_immediate()
        current = float(self.zoom_var.get())
        new_scale = max(ZOOM_MIN, min(current + delta, ZOOM_MAX))
        self._suspend_zoom_sync = True
        self.zoom_var.set(new_scale)
        self._suspend_zoom_sync = False
        self._on_zoom_slider_changed(str(new_scale))

    def _on_preview_wheel(self, event) -> None:
        delta = 0.05 if event.delta > 0 else -0.05
        self._nudge_zoom(delta)

    def toggle_play(self) -> None:
        if not self.preview_engine.is_loaded():
            messagebox.showinfo("Preview", "Select a video first.")
            return
        if self.preview_engine.playing:
            self.stop_playback()
        else:
            self.preview_engine.playing = True
            self._play_started_at = time.perf_counter()
            self._play_start_frame_idx = self.preview_engine.current_frame_idx
            self.play_btn.configure(text="Pause")
            self._play_step()

    def stop_playback(self) -> None:
        self.preview_engine.playing = False
        self.play_btn.configure(text="Play")
        if self._play_after_id is not None:
            self.root.after_cancel(self._play_after_id)
            self._play_after_id = None

    def _play_step(self) -> None:
        if not self.preview_engine.playing or not self.preview_engine.is_loaded():
            return
        elapsed = max(0.0, time.perf_counter() - self._play_started_at)
        target_idx = self._play_start_frame_idx + int(elapsed * self.preview_engine.fps)
        if target_idx >= self.preview_engine.frame_count:
            target_idx = 0
            self._play_start_frame_idx = 0
            self._play_started_at = time.perf_counter()

        frame = self.preview_engine.seek(target_idx)
        if frame is not None:
            self.timeline_var.set(target_idx)
            self._render_preview(frame)

        self._play_after_id = self.root.after(1, self._play_step)

    def set_status(self, message: str, error: bool = False) -> None:
        self.status_var.set(message)
        self.root.update_idletasks()

    def select_video(self) -> None:
        path = filedialog.askopenfilename(
            title="Select video file",
            filetypes=[
                ("Video files", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.wmv"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self._set_video_path(path)

    def _on_video_dropped(self, path: str) -> None:
        self.root.after(0, lambda: self._set_video_path(path))

    def _set_video_path(self, path: str) -> None:
        ext = Path(path).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            messagebox.showerror("Unsupported Format", f"Unsupported video format: {ext}")
            return
        self.video_path_var.set(path)
        self._save_current_editor_state()
        self._load_video_preview(path)

    def _load_video_preview(self, path: str, show_error: bool = True) -> None:
        self.stop_playback()
        if not self.preview_engine.load(path):
            if show_error:
                messagebox.showerror("Video Error", f"Could not open video:\n{path}")
            self.set_status("Failed to load video for preview.")
            return
        self.timeline_var.set(0)
        self.timeline_start_var.set("0:00")
        self.timeline_end_var.set(format_timeline_time(self.preview_engine.duration_sec))
        self.preview_engine.seek(0)
        self._render_preview()
        self._save_current_editor_state()
        self.set_status(
            f"Video loaded: {Path(path).name} - {format_time(self.preview_engine.duration_sec)}, "
            f"{self.preview_engine.frame_count} frames"
        )

    def select_font(self) -> None:
        path = filedialog.askopenfilename(
            title="Select font file",
            filetypes=[("Font files", "*.ttf *.otf *.ttc"), ("All files", "*.*")],
            initialdir=str(Path(DEFAULT_FONT).parent),
        )
        if path:
            self.font_path_var.set(path)

    def select_output_folder(self) -> None:
        path = filedialog.askdirectory(title="Select output folder", initialdir=self.output_folder_var.get())
        if path:
            self.output_folder_var.set(path)

    def select_end_sound(self) -> None:
        path = filedialog.askopenfilename(
            title="Select end sound effect",
            filetypes=[
                ("Audio files", "*.wav *.mp3 *.m4a *.aac *.flac *.ogg"),
                ("All files", "*.*"),
            ],
            initialdir=str(Path(self.end_sound_path_var.get() or DEFAULT_CLAP_SOUND).parent),
        )
        if path:
            self.end_sound_path_var.set(path)

    def _pick_color(self, variable: tk.StringVar) -> None:
        self._push_undo_immediate()
        initial = variable.get() or "#000000"
        _, hex_color = colorchooser.askcolor(color=initial, title="Choose color")
        if hex_color:
            variable.set(hex_color.upper())
            self._finish_edit()

    def pick_bg_color(self) -> None:
        self._pick_color(self.bg_color_var)

    def pick_border_color(self) -> None:
        self._pick_color(self.outline_color_var)

    def save_preset(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Save Preset")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="Preset name:").pack(anchor=tk.W, padx=12, pady=(12, 4))
        name_var = tk.StringVar()
        entry = ttk.Entry(dialog, textvariable=name_var, width=40)
        entry.pack(padx=12)
        entry.focus_set()

        ttk.Label(
            dialog,
            text="Examples: YouTube Shorts Default, Snooker Highlight Style, Black Background Style, Thai Audience Style",
            wraplength=360,
        ).pack(padx=12, pady=(6, 8))

        def do_save() -> None:
            name = name_var.get().strip()
            if not name:
                messagebox.showerror("Preset", "Enter a preset name.", parent=dialog)
                return
            self.settings = self._collect_settings_from_ui()
            path = self.settings_manager.save_preset(name, self.settings)
            self.settings.last_preset = name
            self.settings_manager.save(self.settings)
            self.set_status(f"Preset saved: {path.name}")
            dialog.destroy()

        ttk.Button(dialog, text="Save", command=do_save).pack(pady=12)

    def load_preset(self) -> None:
        presets = self.settings_manager.list_presets()
        if not presets:
            messagebox.showinfo("Presets", "No presets found in the presets folder.")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Load Preset")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="Choose a preset:").pack(anchor=tk.W, padx=12, pady=(12, 4))
        preset_var = tk.StringVar(value=presets[0][0])
        combo = ttk.Combobox(dialog, textvariable=preset_var, values=[n for n, _ in presets], state="readonly", width=42)
        combo.pack(padx=12)

        def do_load() -> None:
            selected = preset_var.get()
            match = next((p for p in presets if p[0] == selected), None)
            if not match:
                messagebox.showerror("Preset", "Preset not found.", parent=dialog)
                return
            self._push_undo_immediate()
            loaded = self.settings_manager.load_preset(match[1])
            loaded.video_path = self.video_path_var.get().strip()
            loaded.last_preset = selected
            self.settings = loaded
            self._apply_settings_to_ui()
            self.settings_manager.save(self.settings)
            self.set_status(f"Preset loaded: {selected}")
            dialog.destroy()

        ttk.Button(dialog, text="Load", command=do_load).pack(pady=12)

    def reset_defaults(self) -> None:
        if not messagebox.askyesno("Reset", "Reset all settings to defaults?"):
            return
        self._push_undo_immediate()
        current_video = self.video_path_var.get().strip()
        self.settings = default_settings()
        self.settings.video_path = current_video
        self._apply_settings_to_ui()
        self.settings_manager.save(self.settings)
        self.set_status("Settings reset to defaults.")

    def auto_assign_export_filename(self) -> None:
        # Find heading from title overlay
        heading = ""
        for overlay in self.settings.text_overlays:
            if isinstance(overlay, dict) and overlay.get("id") == "title":
                heading = overlay.get("text", "")
                break
            elif hasattr(overlay, "id") and overlay.id == "title":
                heading = overlay.text
                break
                
        # Fallback to generated video text text widget if heading is empty
        if not heading:
            try:
                heading = self.generated_video_text_text.get("1.0", "end-1c").strip()
            except Exception:
                pass

        # Split and clean the heading (combine first and second lines)
        if heading:
            lines = [line.strip() for line in heading.splitlines() if line.strip()]
            if len(lines) >= 2:
                heading = f"{lines[0]} {lines[1]}"
            elif len(lines) == 1:
                heading = lines[0]
            else:
                heading = ""
        
        # Clean invalid filename characters
        if heading:
            heading = re.sub(r'[\\/*?:"<>|]', "", heading).strip()
            
        if not heading:
            heading = "shorts_output"
            output_filename = "shorts_output"
        else:
            if not hasattr(self.settings, "export_counts") or self.settings.export_counts is None:
                self.settings.export_counts = {}
                
            std_heading = heading.strip()
            match_key = std_heading.lower()
            
            count = None
            for key, val in self.settings.export_counts.items():
                if key.lower() == match_key:
                    count = val
                    std_heading = key
                    break
                    
            if count is None:
                max_count = max(self.settings.export_counts.values()) if self.settings.export_counts else 0
                count = max_count + 1
                self.settings.export_counts[std_heading] = count
                
            output_filename = f"s {count} {std_heading}"
            
        self.output_filename_var.set(output_filename)
        self.settings.output_filename = output_filename

    def start_export(self) -> None:
        if self.export_thread and self.export_thread.is_alive():
            messagebox.showinfo("Export", "An export is already running.")
            return

        self.stop_playback()
        self.auto_assign_export_filename()
        self._save_current_editor_state()

        try:
            builder = FFmpegBuilder(self.settings)
            builder.validate()
        except ValueError as exc:
            messagebox.showerror("Cannot Export", str(exc))
            self.set_status(str(exc), error=True)
            return

        self.progress.grid()
        self.progress.start(12)
        self.set_status("Exporting video with FFmpeg...")
        export_settings = EditorSettings(**asdict(self.settings))
        self.export_thread = threading.Thread(target=self._run_export, args=(export_settings,), daemon=True)
        self.export_thread.start()

    def _run_export(self, settings: EditorSettings) -> None:
        try:
            builder = FFmpegBuilder(settings)
            cmd = builder.build_command()
            self.root.after(0, lambda: self.set_status("FFmpeg is processing..."))

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            _, stderr = process.communicate()

            if process.returncode != 0:
                raise RuntimeError(stderr.strip() or "FFmpeg export failed.")

            out_path = builder.output_path()
            self.root.after(0, lambda: self._export_success(out_path))
        except Exception as exc:
            self.root.after(0, lambda: self._export_failed(str(exc)))

    def _export_success(self, out_path: Path) -> None:
        self.progress.stop()
        self.progress.grid_remove()
        self._save_current_editor_state()
        self.set_status(f"Export complete: {out_path}")
        self.upload_video_var.set(str(out_path))
        messagebox.showinfo("Export Complete", f"Video saved to:\n{out_path}")

    def _export_failed(self, message: str) -> None:
        self.progress.stop()
        self.progress.grid_remove()
        short = message.splitlines()[-1] if message else "Export failed."
        self.set_status(f"Export failed: {short}", error=True)
        messagebox.showerror("Export Failed", message[:4000])

    def on_close(self) -> None:
        self.stop_playback()
        for after_id in (self._preview_after_id, self._preview_resize_after_id):
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except tk.TclError:
                    pass
        self.preview_engine.release()
        self._save_current_editor_state()
        self.root.destroy()


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    VideoEditorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
