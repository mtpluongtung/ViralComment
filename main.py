import argparse
import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

from logger import get_logger
from reddit_scraper import RedditScraper
from llm_processor import LLMProcessor
from ui_renderer import UIRenderer
from tts_service import TTSService
from video_compiler import VideoCompiler

logger = get_logger("Orchestrator")


async def run_pipeline(
    subreddit: str = "AskReddit",
    time_filter: str = "day",
    voice: str = "en-US-ChristopherNeural",
    bg_video_path: str = None,
    output_filename: str = "viral_short.mp4",
) -> Path:
    """
    Executes the automated end-to-end video generation pipeline:
    1. Scrapes Reddit top post & comments.
    2. Curates and sanitizes text with Google Gemini.
    3. Renders transparent PNG UI cards via Playwright.
    4. Synthesizes voiceover audio with edge-tts.
    5. Assembles final 9:16 video with FFmpeg.
    """
    logger.info("==================================================")
    logger.info("   STARTING AUTOMATED VIRAL SHORT GENERATOR      ")
    logger.info("==================================================")

    # 1. Scrape Reddit
    logger.info(f"Step 1: Scraping top thread from r/{subreddit}...")
    scraper = RedditScraper()
    post = scraper.fetch_top_post(
        subreddit_name=subreddit,
        time_filter=time_filter,
        comment_limit=15,
        max_child_replies=2,
    )

    # 2. Process with Google Gemini (LLM)
    logger.info("Step 2: Processing thread content with Gemini 1.5 Flash...")
    llm = LLMProcessor()
    processed_content = llm.process_thread(post)

    logger.info(f"Viral Topic Score: {processed_content.topic_score}/10")
    logger.info(f"Selected Hook: {processed_content.selected_title_tts}")
    for idx, c in enumerate(processed_content.comments, start=1):
        logger.info(f"  Comment #{idx} by u/{c.original_author} ({c.score_display}): {c.display_text[:60]}...")

    # 3. Render UI Cards (Playwright Async)
    logger.info("Step 3: Rendering transparent HTML/CSS cards to PNG...")
    renderer = UIRenderer(output_dir="output/cards")
    card_paths = await renderer.generate_cards(
        processed_data=processed_content,
        raw_title=post.title,
        subreddit=post.subreddit,
        author=post.author,
        post_score=post.score,
    )

    # 4. Generate TTS Audio (edge-tts)
    logger.info(f"Step 4: Generating TTS audio clips (Voice: {voice})...")
    tts = TTSService(voice=voice, output_dir="output/audio")
    audio_segments = await tts.generate_speech_segments(processed_content)

    # 5. Assemble Video (FFmpeg)
    logger.info("Step 5: Compiling final 1080x1920 video with FFmpeg...")
    compiler = VideoCompiler(output_dir="output/final")
    final_video_path = compiler.compile(
        card_paths=card_paths,
        audio_segments=audio_segments,
        background_video_path=bg_video_path,
        output_filename=output_filename,
    )

    logger.info("==================================================")
    logger.info("   PIPELINE EXECUTION COMPLETED SUCCESSFULLY!     ")
    logger.info(f"   Final Video: {final_video_path.resolve()}")
    logger.info("==================================================")
    return final_video_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automated YouTube Shorts generator from viral Reddit threads."
    )
    parser.add_argument(
        "--subreddit",
        type=str,
        default="AskReddit",
        help="Subreddit to scrape (e.g., AskReddit, UnethicalLifeProTips). Default: AskReddit",
    )
    parser.add_argument(
        "--time-filter",
        type=str,
        default="day",
        choices=["day", "week", "month", "all"],
        help="Reddit top time window. Default: day",
    )
    parser.add_argument(
        "--voice",
        type=str,
        default=os.getenv("DEFAULT_VOICE", "en-US-ChristopherNeural"),
        help="edge-tts voice identifier. Default: en-US-ChristopherNeural",
    )
    parser.add_argument(
        "--bg-video",
        type=str,
        default=os.getenv("BG_VIDEO_PATH", None),
        help="Path to background video (e.g., Minecraft gameplay). Auto-generates if omitted.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="viral_short.mp4",
        help="Output video file name. Default: viral_short.mp4",
    )
    return parser.parse_args()


def main() -> None:
    # Load environment variables from .env file
    load_dotenv()

    # Pre-flight credential check
    required_keys = ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "GEMINI_API_KEY"]
    missing = [k for k in required_keys if not os.getenv(k)]
    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        logger.error("Please configure them in your .env file or environment.")
        sys.exit(1)

    args = parse_args()

    try:
        asyncio.run(
            run_pipeline(
                subreddit=args.subreddit,
                time_filter=args.time_filter,
                voice=args.voice,
                bg_video_path=args.bg_video,
                output_filename=args.output,
            )
        )
    except KeyboardInterrupt:
        logger.warning("Pipeline interrupted by user.")
        sys.exit(130)
    except Exception as exc:
        logger.critical(f"Fatal pipeline error: {exc}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
