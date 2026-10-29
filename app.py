import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Dict, Any, Optional

from dotenv import load_dotenv, set_key
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from logger import get_logger
from reddit_scraper import RedditScraper, RedditPost
from llm_processor import LLMProcessor, ProcessedVideoContent
from ui_renderer import UIRenderer
from tts_service import TTSService
from video_compiler import VideoCompiler

# Load initial environment variables
load_dotenv()

logger = get_logger("WebApp")

app = FastAPI(title="ViralShorts AI Studio", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Directories
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
UPLOADS_DIR = BASE_DIR / "uploads"
TEMPLATES_DIR = BASE_DIR / "templates"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
(OUTPUT_DIR / "cards").mkdir(parents=True, exist_ok=True)
(OUTPUT_DIR / "audio").mkdir(parents=True, exist_ok=True)
(OUTPUT_DIR / "final").mkdir(parents=True, exist_ok=True)

# Mount static files to serve cards, audio, and compiled videos directly
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")


class KeysPayload(BaseModel):
    reddit_client_id: Optional[str] = None
    reddit_client_secret: Optional[str] = None
    gemini_api_key: Optional[str] = None


class PreviewPayload(BaseModel):
    subreddit: str = "AskReddit"
    time_filter: str = "day"


class CompileEditedPayload(BaseModel):
    post: Dict[str, Any]
    processed: Dict[str, Any]
    voice: str = "en-US-ChristopherNeural"
    bg_video: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = TEMPLATES_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return index_file.read_text(encoding="utf-8")


@app.get("/api/status")
async def get_system_status():
    reddit_id = os.getenv("REDDIT_CLIENT_ID")
    reddit_secret = os.getenv("REDDIT_CLIENT_SECRET")
    gemini_key = os.getenv("GEMINI_API_KEY")

    is_configured = bool(reddit_id and reddit_secret and gemini_key)
    return {
        "configured": is_configured,
        "has_reddit": bool(reddit_id and reddit_secret),
        "has_gemini": bool(gemini_key),
    }


@app.post("/api/save-keys")
async def save_api_keys(payload: KeysPayload):
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        env_file.touch()

    if payload.reddit_client_id:
        os.environ["REDDIT_CLIENT_ID"] = payload.reddit_client_id
        set_key(str(env_file), "REDDIT_CLIENT_ID", payload.reddit_client_id)
    if payload.reddit_client_secret:
        os.environ["REDDIT_CLIENT_SECRET"] = payload.reddit_client_secret
        set_key(str(env_file), "REDDIT_CLIENT_SECRET", payload.reddit_client_secret)
    if payload.gemini_api_key:
        os.environ["GEMINI_API_KEY"] = payload.gemini_api_key
        set_key(str(env_file), "GEMINI_API_KEY", payload.gemini_api_key)

    logger.info("API keys successfully updated via Web UI.")
    return {"success": True}


@app.post("/api/upload-bg")
async def upload_background_video(file: UploadFile = File(...)):
    filename = file.filename or "custom_bg.mp4"
    save_path = UPLOADS_DIR / filename
    with save_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    logger.info(f"Custom background video uploaded: {save_path.name}")
    return {"success": True, "filename": filename, "path": f"/uploads/{filename}"}


@app.post("/api/preview-content")
async def preview_content(payload: PreviewPayload):
    """Fetches Reddit content and analyzes with Gemini without compiling video."""
    try:
        scraper = RedditScraper()
        post = scraper.fetch_top_post(
            subreddit_name=payload.subreddit,
            time_filter=payload.time_filter,
            comment_limit=15,
            max_child_replies=2,
        )

        llm = LLMProcessor()
        processed = llm.process_thread(post)

        return {
            "success": True,
            "post": post.model_dump(),
            "processed": processed.model_dump(),
        }
    except Exception as e:
        logger.error(f"Error previewing content: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/generate-stream")
async def generate_stream(
    subreddit: str = "AskReddit",
    time_filter: str = "day",
    voice: str = "en-US-ChristopherNeural",
    bg_video: Optional[str] = None,
):
    """
    Server-Sent Events (SSE) streaming endpoint that executes the full pipeline
    and yields real-time logs and progress updates to the browser.
    """
    async def event_generator():
        def sse(event_type: str, data: Dict[str, Any]) -> str:
            payload = {"type": event_type, **data}
            return f"data: {json.dumps(payload)}\n\n"

        try:
            yield sse("log", {"message": f"Kết nối thành công. Đang cào bài từ r/{subreddit}...", "level": "info"})
            yield sse("progress", {"percent": 10, "stage": f"Đang cào bài r/{subreddit}..."})

            # 1. Scrape Reddit
            scraper = RedditScraper()
            post = scraper.fetch_top_post(
                subreddit_name=subreddit,
                time_filter=time_filter,
                comment_limit=15,
                max_child_replies=2,
            )
            yield sse("log", {"message": f"Đã cào bài: '{post.title[:50]}...' ({len(post.comments)} comments)", "level": "info"})
            yield sse("progress", {"percent": 30, "stage": "Gemini đang chấm điểm & chọn lọc comments..."})

            # 2. Process with Gemini
            llm = LLMProcessor()
            processed = llm.process_thread(post)
            yield sse("content_ready", {
                "post": post.model_dump(),
                "processed": processed.model_dump(),
            })
            yield sse("log", {"message": f"Gemini hoàn tất! Virality Score: {processed.topic_score}/10", "level": "success"})
            yield sse("progress", {"percent": 55, "stage": "Playwright đang render card HTML sang PNG..."})

            # 3. Render UI Cards (Playwright Async)
            renderer = UIRenderer(output_dir=str(OUTPUT_DIR / "cards"))
            card_paths = await renderer.generate_cards(
                processed_data=processed,
                raw_title=post.title,
                subreddit=post.subreddit,
                author=post.author,
                post_score=post.score,
            )
            card_web_urls = [f"/output/cards/{p.name}" for p in card_paths]
            yield sse("cards_ready", {"cards": card_web_urls})
            yield sse("log", {"message": f"Render thành công {len(card_paths)} card trong suốt (PNG)!", "level": "info"})
            yield sse("progress", {"percent": 75, "stage": f"Edge-TTS đang tạo giọng đọc ({voice})..."})

            # 4. Synthesize TTS
            tts = TTSService(voice=voice, output_dir=str(OUTPUT_DIR / "audio"))
            audio_segments = await tts.generate_speech_segments(processed)
            total_duration = sum(s.duration for s in audio_segments)
            yield sse("log", {"message": f"TTS hoàn tất: {len(audio_segments)} audio clips, tổng {total_duration:.1f}s", "level": "info"})
            yield sse("progress", {"percent": 88, "stage": "FFmpeg đang ghép video 9:16 & hiệu ứng pop SFX..."})

            # 5. Compile Video
            resolved_bg = str(UPLOADS_DIR / bg_video) if bg_video and (UPLOADS_DIR / bg_video).exists() else None
            compiler = VideoCompiler(output_dir=str(OUTPUT_DIR / "final"))
            final_mp4 = compiler.compile(
                card_paths=card_paths,
                audio_segments=audio_segments,
                background_video_path=resolved_bg,
                output_filename="final_viral_short.mp4",
            )

            video_web_url = f"/output/final/{final_mp4.name}"
            yield sse("log", {"message": f"Biên tập video hoàn tất! Cắt chính xác +0.2s sau audio cuối.", "level": "success"})
            yield sse("completed", {"video_url": video_web_url})

        except Exception as e:
            logger.error(f"Streaming error: {e}", exc_info=True)
            yield sse("error", {"message": str(e)})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/compile-edited")
async def compile_edited_content(payload: CompileEditedPayload):
    """
    Renders and compiles video from content that the user inspected
    or manually edited in the Web UI.
    """
    try:
        raw_post = RedditPost.model_validate(payload.post)
        processed = ProcessedVideoContent.model_validate(payload.processed)

        # 1. Render Cards
        renderer = UIRenderer(output_dir=str(OUTPUT_DIR / "cards"))
        card_paths = await renderer.generate_cards(
            processed_data=processed,
            raw_title=raw_post.title,
            subreddit=raw_post.subreddit,
            author=raw_post.author,
            post_score=raw_post.score,
        )
        card_web_urls = [f"/output/cards/{p.name}" for p in card_paths]

        # 2. TTS
        tts = TTSService(voice=payload.voice, output_dir=str(OUTPUT_DIR / "audio"))
        audio_segments = await tts.generate_speech_segments(processed)

        # 3. FFmpeg Video Compiler
        compiler = VideoCompiler(output_dir=str(OUTPUT_DIR / "final"))
        resolved_bg = str(UPLOADS_DIR / payload.bg_video) if payload.bg_video and (UPLOADS_DIR / payload.bg_video).exists() else None
        final_mp4 = compiler.compile(
            card_paths=card_paths,
            audio_segments=audio_segments,
            background_video_path=resolved_bg,
            output_filename="final_viral_short.mp4",
        )

        return {
            "success": True,
            "cards": card_web_urls,
            "video_url": f"/output/final/{final_mp4.name}",
        }
    except Exception as e:
        logger.error(f"Error compiling edited content: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    logger.info("Starting ViralShorts Web Studio on http://localhost:8000")
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
