# 🎬 ViralShorts AI Studio (ViralComment)

An automated, modular pipeline that transforms viral Reddit threads into YouTube Shorts (9:16 vertical videos) with AI curation, responsive dynamic UI cards, neural voiceover, and synchronized video compilation.

---

## 🌟 Key Features

- **Reddit Scraper (`praw`):** Scrapes the top posts of the day and top 15 comments along with nested crowd reactions from subreddits like `r/AskReddit` and `r/UnethicalLifeProTips`.
- **LLM Content Curation (`google-genai`):** Evaluates viral potential (1-10), formats natural-sounding spoken TTS text (expands acronyms like AITA, OP, TL;DR), and censors visual display text for YouTube advertiser-friendliness.
- **Dynamic UI Rendering (`playwright` async):** Injects Reddit data into modern Threads/X dark-mode HTML/CSS cards and captures transparent PNG screenshots (`omit_background=True`).
- **Neural Text-To-Speech (`edge-tts`):** Generates high-quality voiceover audio (English & Vietnamese voices) and precisely measures segment durations.
- **Video Compiler (`ffmpeg-python`):** Chains gameplay background footage, transparent card overlays, voiceover audio, and transition SFX (pop/whoosh) into a 1080x1920 (9:16) video with a precise +0.2s seamless loop cut.
- **Web UI Dashboard:** Built with **FastAPI** + **Tailwind CSS**, featuring real-time Server-Sent Events (SSE) progress streaming, script inspection/editing, and a 9:16 video player.

---

## 🚀 Quick Start

### 1. Clone the repository
```bash
git clone https://github.com/mtpluongtung/ViralComment.git
cd ViralComment
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Configure credentials
Copy `.env.example` to `.env` and fill in your keys:
```bash
cp .env.example .env
```
Or configure keys directly in the Web UI Settings modal.

Required environment variables:
- `REDDIT_CLIENT_ID`
- `REDDIT_CLIENT_SECRET`
- `GEMINI_API_KEY`

---

## 🖥️ Usage

### Option 1: Modern Web UI (Recommended)
Launch the interactive web dashboard:
```bash
python app.py
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser.

### Option 2: CLI Terminal Execution
Run the end-to-end command line orchestrator:
```bash
# Basic run with r/AskReddit
python main.py

# Custom subreddit, time window, and gameplay background video
python main.py --subreddit UnethicalLifeProTips --time-filter day --bg-video assets/gameplay.mp4 --output short.mp4
```

---

## 📁 Project Structure

```
├── app.py                # FastAPI Web Server & SSE Streaming API
├── main.py               # CLI Orchestrator
├── reddit_scraper.py     # PRAW Reddit Scraper
├── llm_processor.py      # Google Gemini 1.5 Flash structured processing
├── ui_renderer.py        # Playwright HTML/CSS to transparent PNG cards
├── tts_service.py        # Edge-TTS speech synthesis & duration tracking
├── video_compiler.py     # FFmpeg 9:16 video compilation & SFX overlay
├── logger.py             # Centralized colored logging
├── templates/
│   └── index.html        # Modern Dark Studio Web UI
├── requirements.txt      # Python dependencies
├── .env.example          # Environment variable template
└── .gitignore
```
