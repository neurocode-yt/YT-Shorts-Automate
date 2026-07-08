# YT Shorts Automate

A Windows desktop app for turning videos into vertical YouTube Shorts, TikTok, Reels, and Facebook Shorts with draggable video/text layers, presets, preview playback, and FFmpeg export.

## Features

- Import common video formats such as MP4, MOV, MKV, AVI, WebM, M4V, and WMV
- Live 1080x1920 vertical preview
- Drag video and text elements directly on the preview
- Optional center-lock alignment for video and text layers
- Independent title/footer text layers
- Per-layer text color, line 1 color, font, border, shadow, and background box
- Larger first-line font size support
- Zoom/scale control for the video clip
- Timeline preview with playback controls
- End sound effect support with a draggable green clap marker
- Save/load style presets
- Automatic settings persistence between sessions
- FFmpeg export with H.264/AAC MP4 output

## Requirements

- Windows
- Python 3.10+
- FFmpeg installed

Install Python packages:

```powershell
pip install -r requirements.txt
```

Tkinter is included with the standard Windows Python installer.

## FFmpeg

The app first looks for `ffmpeg` on your system `PATH`. It can also auto-detect common WinGet and CapCut FFmpeg locations.

Recommended install:

```powershell
winget install Gyan.FFmpeg
```

Restart PowerShell after installing FFmpeg.

## Run

```powershell
python main.py
```

Or from the parent folder:

```powershell
cd video_editor_app
python main.py
```

## Usage

1. Click **Browse** in Video Input and select a video.
2. Use the live preview to drag the video, title text, and footer text.
3. Use **Video & Canvas** for background color, position, zoom, crop mode, and center alignment.
4. Use **Text Style** for font, size, line 1 size, colors, border, shadow, and text placement.
5. Use **Export** to choose output folder, quality, file name, and end sound settings.
6. Drag the green **CLAP** marker on the timeline to choose when the clapping sound starts.
7. Click **Export Video**.

## Presets

Presets are stored in the `presets/` folder as JSON files. Use **Save Preset** and **Load Preset** inside the app.

## Autosave

The app automatically saves the current editor state locally in `settings.json`, including:

- Text content and styles
- Text/video positions
- Zoom level
- Center alignment
- End sound settings
- Export settings
- Last selected video path

`settings.json` is intentionally ignored by Git because it contains local machine paths.

## Project Structure

```text
video_editor_app/
  main.py
  requirements.txt
  presets/
  output/
```

## Notes

- `output/` is ignored by Git because it contains generated videos.
- `settings.json` is ignored by Git because it contains local paths.
- For custom fonts, choose a `.ttf`, `.otf`, or `.ttc` file from your system.
