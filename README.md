# VanGogh

A drawing practice app built with PySide6.

Load a random reference image from a local folder or pull random ones from the web, set a countdown timer, and draw. The interface stays out of your way — controls auto-hide and reappear when you move the mouse.

![Python](https://img.shields.io/badge/python-3.10%2B-blue) ![PySide6](https://img.shields.io/badge/PySide6-6.x-green)

## Features

- **Local folders** — recursively scans for JPG, PNG, GIF, BMP, WEBP
- **Web images** — fetches random photos from [loremflickr.com](https://loremflickr.com) by keyword
- **Countdown timer** — presets from 30 s to 30 min, or custom duration
- **GPU zoom & pan** — smooth zoom with scroll wheel, centered on cursor; double-click to fit/zoom
- **Flip** — mirror image horizontally
- **Grid overlay** — grid with pan offset (you can make grid smaller and bigger)
- **S/W** — black & white mode
- **Brightness & contrast** — adjustable via floating panel
- **Background preloading** — next image loads while you draw
- **Recent items** — last used folders and keywords are remembered across sessions
- **Auto-hide controls** — navbar disappears after 3s of inactivity, stays visible on hover

## Requirements

```
PySide6
Pillow
requests
```

## Installation

```bash
python -m venv venv
source venv/bin/activate
pip install PySide6 Pillow requests
```

## Usage

```bash
python main.py
```

Choose a local image folder or enter a search keyword, pick a timer duration, and start.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Space` | Pause / resume timer |
| `N` | Next image |
| `T` | Restart timer |
| `F` | Flip horizontal |
| `G` | Toggle grid |
| `B` | Toggle B&W |
| `A` | Open adjust panel |
| `R` | Reset view |
| `H` | Show / hide navbar |
| `+` / `-` | Grid divisions |
| `F11` | Fullscreen |
| `F1` | Help |
| `Escape` | Close |

## Mouse Controls

| Input | Action |
|-------|--------|
| Scroll wheel | Zoom in / out, centered on cursor |
| Left drag | Pan image |
| Double-click (fit) | Zoom to 2× at cursor position |
| Double-click (zoomed) | Fit image to window |
| Right drag | Shift grid overlay offset |
