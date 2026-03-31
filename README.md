# 🎵 YTDL — YouTube to MP3 & MP4 Converter

![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=flat-square&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-2.x-000000?style=flat-square&logo=flask&logoColor=white)
![yt-dlp](https://img.shields.io/badge/yt--dlp-latest-FF0000?style=flat-square&logo=youtube&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-22c55e?style=flat-square)
![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey?style=flat-square)

A fast, local YouTube converter that downloads **MP3 audio** and **MP4 video** at full original quality — with no file size limits, no throttling, and support for videos over **4+ hours long**.

Everything runs on your own machine. No data is sent to third-party servers.

---

## ✨ Features

- 🎵 **MP3 downloads** — best available audio quality, converted via ffmpeg
- 🎬 **MP4 downloads** — full resolution video up to 8K (merges best video + audio streams)
- 📏 **No length limit** — handles videos, full concerts, lectures, and streams over 4 hours
- 🎚️ **Quality selector** — auto-detects available resolutions after fetching the URL
- 📊 **Live progress bar** — real-time step-by-step conversion tracking
- 🔒 **100% local** — all processing happens on your machine
- ⚡ **Maximum speed** — downloads straight from YouTube's CDN at full bandwidth

---

## 🖥️ Preview

```
┌─────────────────────────────────────────────────┐
│  ● Audio & Video Downloader                     │
│                                                 │
│  YouTube Convert                                │
│  MP3 & MP4 · Any length · Any quality          │
│                                                 │
│  [ https://youtube.com/watch?v=... ]  [ Fetch ] │
│                                                 │
│  🖼 Thumbnail   Title of Video                  │
│                 Duration: 4:32:10               │
│                                                 │
│  Format:  [ MP3 | MP4 ]                         │
│  Quality: [ 1080p ▾ ]                           │
│                                                 │
│       [ Convert & Download ]                    │
└─────────────────────────────────────────────────┘
```

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.8+**
- **ffmpeg** — required for audio conversion and video merging

#### Install ffmpeg

| Platform | Command |
|----------|---------|
| macOS | `brew install ffmpeg` |
| Ubuntu/Debian | `sudo apt install ffmpeg` |
| Windows | Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH |

---

### Installation

**1. Clone the repository**
```bash
git clone https://github.com/YOUR_USERNAME/yt-converter.git
cd yt-converter
```

**2. Install Python dependencies**
```bash
pip install -r requirements.txt
```

**3. Start the backend server**
```bash
python app.py
```

The API will be running at `http://localhost:5000`

**4. Open the frontend**

Open `index.html` in your browser (double-click or drag into browser).

---

## 🎮 Usage

1. **Paste** a YouTube URL into the input field
2. Click **Fetch** to load the video title, duration, and available qualities
3. Select **MP3** or **MP4** as your format
4. For MP4, choose your desired **resolution** from the dropdown
5. Click **Convert & Download**
6. Watch the **live progress bar** as it downloads and processes
7. Click **Download File** when complete

Downloaded files are saved to the `downloads/` folder next to `app.py`.

---

## 🗂️ Project Structure

```
yt-converter/
├── app.py            # Flask backend — handles yt-dlp, conversion, job tracking
├── index.html        # Frontend UI — dark-themed, responsive, progress tracking
├── requirements.txt  # Python dependencies
├── .gitignore        # Excludes downloads/, caches, OS files
├── README.md         # This file
└── downloads/        # Output folder (auto-created, gitignored)
```

---

## ⚙️ How It Works

```
Browser (index.html)
    │
    ├─ POST /api/info       → Fetches video title, duration, available qualities
    ├─ POST /api/convert    → Starts a background download job, returns job_id
    ├─ GET  /api/status/:id → Polls job progress (status + % complete)
    └─ GET  /api/download/:id → Streams the completed file to the browser
```

The backend uses `yt-dlp` under the hood:
- **MP3**: extracts best audio stream → converts to MP3 via ffmpeg
- **MP4**: downloads best video + best audio for chosen resolution → merges with ffmpeg

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python, Flask, flask-cors |
| Downloader | yt-dlp |
| Audio/Video processing | ffmpeg |
| Frontend | Vanilla HTML/CSS/JS |
| Fonts | Syne, DM Mono (Google Fonts) |

---

## 📋 API Reference

| Endpoint | Method | Body | Description |
|----------|--------|------|-------------|
| `/api/info` | POST | `{ url }` | Get video metadata and available qualities |
| `/api/convert` | POST | `{ url, format, quality }` | Start a conversion job |
| `/api/status/:job_id` | GET | — | Poll job status and progress |
| `/api/download/:job_id` | GET | — | Download the converted file |

---

## ⚠️ Legal Notice

This tool is intended for **personal use only**. Please respect YouTube's [Terms of Service](https://www.youtube.com/t/terms) and only download content you have the right to download, such as your own videos or content with a Creative Commons license.

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgements

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — the powerful downloader that makes this possible
- [ffmpeg](https://ffmpeg.org/) — audio/video processing
- [Flask](https://flask.palletsprojects.com/) — lightweight Python web framework
