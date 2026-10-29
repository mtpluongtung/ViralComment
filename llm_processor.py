import json
import os
import re
from typing import List, Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

from logger import get_logger
from reddit_scraper import RedditPost

logger = get_logger("LLMProcessor")


class SelectedComment(BaseModel):
    """Processed comment ready for UI rendering and TTS synthesis."""
    original_author: str = Field(..., description="Username of the comment author")
    score_display: str = Field(..., description="Humanized score e.g. '14.2k' or '850'")
    cleaned_tts_text: str = Field(
        ...,
        description="Spoken text for TTS. Expand acronyms (e.g., OP -> original poster, AITA -> am I the jerk, "
                    "TL;DR -> too long didn't read). Remove or rephrase harsh profanity to ensure monetization."
    )
    display_text: str = Field(
        ...,
        description="Text displayed on screen card. Must mask profanity with asterisks (e.g., f***, s***) "
                    "to prevent YouTube OCR demonetization."
    )


class ProcessedVideoContent(BaseModel):
    """Strict JSON schema output requested for the video pipeline."""
    topic_score: int = Field(..., ge=1, le=10, description="Engagement/virality score between 1 and 10")
    selected_title_tts: str = Field(..., description="Engaging, concise title hook formatted for clear TTS audio")
    comments: List[SelectedComment] = Field(
        ...,
        description="Exactly 4 curated, high-impact comments selected for narrative flow",
        min_length=4,
        max_length=4,
    )


class LLMProcessor:
    """Processes scraped Reddit threads with Google Gemini 1.5 Flash."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-1.5-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables or parameters.")

        self.model = model
        logger.info(f"Initializing Gemini Client with model: {self.model}")
        self.client = genai.Client(api_key=self.api_key)

    def process_thread(self, post: RedditPost) -> ProcessedVideoContent:
        """
        Analyzes the Reddit post and comment tree, selecting 4 top comments,
        cleaning them for TTS, censoring profanity for OCR UI display,
        and returning a strictly structured ProcessedVideoContent.
        """
        logger.info(f"Analyzing thread '{post.title}' ({len(post.comments)} comments)...")

        # Prepare thread context for the prompt
        thread_payload = {
            "title": post.title,
            "author": post.author,
            "score": post.score,
            "subreddit": post.subreddit,
            "comments": [
                {
                    "author": c.author,
                    "score": c.score,
                    "body": c.body,
                    "replies": [{"author": r.author, "score": r.score, "body": r.body} for r in c.child_replies],
                }
                for c in post.comments
            ],
        }

        system_instruction = (
            "You are an expert viral content producer for YouTube Shorts and TikTok.\n"
            "Your job is to select the top 4 most humorous, jaw-dropping, or insightful comments from this Reddit thread.\n"
            "Rules:\n"
            "1. Output MUST strictly conform to the provided JSON schema.\n"
            "2. topic_score: Rate the viral potential of this topic from 1 to 10.\n"
            "3. selected_title_tts: Create a spoken hook version of the title. Make it punchy, conversational, "
            "and natural for audio synthesis.\n"
            "4. comments: Pick EXACTLY 4 distinct comments. You may integrate a punchy child reply into the comment if it elevates the reaction.\n"
            "5. cleaned_tts_text: Format for spoken text to sound natural. Spell out Reddit abbreviations (e.g. OP -> 'original poster', "
            "AITA -> 'Am I the jerk', IIRC -> 'if I recall correctly', TLDR -> 'In short'). Replace slurs and harsh profanity with clean conversational alternatives.\n"
            "6. display_text: Keep the original humor and tone, but replace vulgar words with asterisks (e.g., 'f***', 'sh*t', 'b****') "
            "to prevent YouTube automated OCR demonetization.\n"
            "7. score_display: Format numbers nicely (e.g., 14200 -> '14.2k', 890 -> '890')."
        )

        user_content = f"Here is the Reddit thread data in JSON format:\n{json.dumps(thread_payload, indent=2)}"

        try:
            logger.info("Dispatching request to Gemini API with structured JSON output...")
            response = self.client.models.generate_content(
                model=self.model,
                contents=user_content,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_schema=ProcessedVideoContent,
                    temperature=0.3,
                ),
            )

            raw_text = response.text.strip()
            # Clean possible markdown wrap if model returns code fence
            if raw_text.startswith("```"):
                raw_text = re.sub(r"^```(?:json)?\n?", "", raw_text)
                raw_text = re.sub(r"\n?```$", "", raw_text)

            parsed = ProcessedVideoContent.model_validate_json(raw_text)
            logger.info(
                f"Gemini processing complete! Virality Score: {parsed.topic_score}/10, "
                f"Selected {len(parsed.comments)} comments."
            )
            return parsed

        except Exception as e:
            logger.error(f"Error during LLM processing: {e}")
            raise
