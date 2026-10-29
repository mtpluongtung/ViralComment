import asyncio
import os
import subprocess
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel
import edge_tts
from mutagen.mp3 import MP3

from logger import get_logger
from llm_processor import ProcessedVideoContent

logger = get_logger("TTSService")


class AudioSegment(BaseModel):
    """Metadata representing a synthesized voiceover segment."""
    index: int
    file_path: Path
    duration: float
    text: str

    class Config:
        arbitrary_types_allowed = True


class TTSService:
    """Generates natural text-to-speech audio files using edge-tts."""

    def __init__(
        self,
        voice: Optional[str] = None,
        output_dir: str = "output/audio",
        rate: str = "+3%",
        pitch: str = "+0Hz",
    ):
        self.voice = voice or os.getenv("DEFAULT_VOICE", "en-US-ChristopherNeural")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.rate = rate
        self.pitch = pitch
        logger.info(f"Initialized TTSService with Voice='{self.voice}', Rate='{self.rate}'")

    def _get_audio_duration(self, audio_path: Path) -> float:
        """Calculates precise audio duration using mutagen with an ffprobe fallback."""
        try:
            audio = MP3(str(audio_path))
            return float(audio.info.length)
        except Exception:
            # Fallback to ffprobe
            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            return float(result.stdout.strip())

    async def _synthesize_file(self, text: str, output_path: Path) -> AudioSegment:
        """Synthesizes a single audio segment using edge-tts."""
        communicate = edge_tts.Communicate(
            text=text,
            voice=self.voice,
            rate=self.rate,
            pitch=self.pitch,
        )
        await communicate.save(str(output_path))
        duration = self._get_audio_duration(output_path)
        logger.info(f"Synthesized '{output_path.name}' -> Duration: {duration:.2f}s")
        return AudioSegment(
            index=0,
            file_path=output_path,
            duration=duration,
            text=text,
        )

    async def generate_speech_segments(
        self,
        processed_data: ProcessedVideoContent,
    ) -> List[AudioSegment]:
        """
        Synthesizes TTS audio for the title hook and all 4 curated comments.
        Returns ordered AudioSegment objects with duration and paths.
        """
        logger.info("Starting batch speech synthesis for Title and Comments...")
        segments: List[AudioSegment] = []

        # 1. Synthesize Title
        title_path = self.output_dir / "audio_0_title.mp3"
        title_seg = await self._synthesize_file(processed_data.selected_title_tts, title_path)
        title_seg.index = 0
        segments.append(title_seg)

        # 2. Synthesize Comments
        for idx, comment in enumerate(processed_data.comments, start=1):
            comment_path = self.output_dir / f"audio_{idx}_comment.mp3"
            comment_seg = await self._synthesize_file(comment.cleaned_tts_text, comment_path)
            comment_seg.index = idx
            segments.append(comment_seg)

        total_audio_duration = sum(s.duration for s in segments)
        logger.info(
            f"Speech synthesis complete. Total {len(segments)} segments | "
            f"Total duration: {total_audio_duration:.2f}s"
        )
        return segments
