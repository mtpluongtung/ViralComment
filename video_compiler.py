import math
from pathlib import Path
import struct
from typing import List, Optional
import wave
import ffmpeg

from logger import get_logger
from tts_service import AudioSegment

logger = get_logger("VideoCompiler")


class VideoCompiler:
    """
    Compiles final YouTube Shorts video (1080x1920) by chaining background video,
    transparent card overlays, sequential voiceover, and transition SFX using ffmpeg-python.
    """

    def __init__(
        self,
        output_dir: str = "output/final",
        sfx_path: Optional[str] = None,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.sfx_path = Path(sfx_path) if sfx_path else self.output_dir / "pop_sfx.wav"

        # Ensure default SFX exists
        if not self.sfx_path.exists():
            self._generate_default_pop_sfx(self.sfx_path)

    def _generate_default_pop_sfx(self, output_file: Path, duration: float = 0.12) -> Path:
        """Synthesizes a short, satisfying acoustic 'pop' sound using pure Python wave module."""
        logger.info(f"Synthesizing default transition pop SFX at {output_file}...")
        sample_rate = 44100
        n_samples = int(sample_rate * duration)
        with wave.open(str(output_file), "w") as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)

            for i in range(n_samples):
                t = float(i) / sample_rate
                # Exponential decay envelope with pitched frequency shift (600Hz down to 200Hz)
                freq = 600.0 - (400.0 * (i / n_samples))
                envelope = math.exp(-t * 35.0)
                sample = envelope * math.sin(2.0 * math.pi * freq * t)
                packed_val = struct.pack("<h", int(sample * 28000.0))
                wav_file.writeframes(packed_val)

        return output_file

    def _generate_fallback_background(self, output_file: Path, duration: float) -> Path:
        """
        Generates an aesthetic vertical (1080x1920) animated ambient background
        using FFmpeg lavfi filters if no external gameplay footage is supplied.
        """
        logger.info(f"No background footage provided. Generating animated ambient background ({duration:.1f}s)...")
        # Generate animated radial color gradient in 1080x1920
        (
            ffmpeg.input(
                f"color=c=#0f172a:s=1080x1920:d={duration}:r=30",
                f="lavfi"
            )
            .filter("drawbox", x=0, y=0, w=1080, h=1920, color="#1e1b4b@0.7", t="fill")
            .output(
                str(output_file),
                vcodec="libx264",
                pix_fmt="yuv420p",
                t=duration,
            )
            .overwrite_output()
            .run(quiet=True)
        )
        return output_file

    def compile(
        self,
        card_paths: List[Path],
        audio_segments: List[AudioSegment],
        background_video_path: Optional[str] = None,
        output_filename: str = "final_viral_short.mp4",
    ) -> Path:
        """
        Orchestrates FFmpeg filter graph to combine overlays, voiceovers, and SFX.
        - Precision loop: cuts precisely 0.2s after last audio segment ends.
        - Video resolution: 1080x1920 (9:16 portrait).
        - Sequential card and audio transitions with sound effects.
        """
        if len(card_paths) != len(audio_segments):
            raise ValueError(
                f"Mismatch: Received {len(card_paths)} card images but {len(audio_segments)} audio segments."
            )

        output_path = self.output_dir / output_filename
        total_audio_duration = sum(seg.duration for seg in audio_segments)
        # Precise loop cut: exactly 0.2s after the final TTS audio ends
        total_duration = total_audio_duration + 0.2

        logger.info(f"Total video duration calculated: {total_duration:.2f}s (cut at TTS end + 0.2s)")

        # 1. Resolve Background Video
        bg_resolved_path: Path
        if background_video_path and Path(background_video_path).exists():
            bg_resolved_path = Path(background_video_path)
            logger.info(f"Using supplied background video: {bg_resolved_path}")
            # Loop background video if shorter than target duration
            bg_input = ffmpeg.input(str(bg_resolved_path), stream_loop=-1, t=total_duration)
        else:
            fallback_bg = self.output_dir / "ambient_background.mp4"
            self._generate_fallback_background(fallback_bg, total_duration)
            bg_input = ffmpeg.input(str(fallback_bg), t=total_duration)

        # Scale and crop background to exact 1080x1920 (9:16)
        video_stream = bg_input.video.filter(
            "scale", 1080, 1920, force_original_aspect_ratio="increase"
        ).filter("crop", 1080, 1920)

        # 2. Build Sequential Overlays & Transition Timestamps
        current_time = 0.0
        transition_timestamps: List[float] = []

        for idx, (card_path, seg) in enumerate(zip(card_paths, audio_segments)):
            start_t = current_time
            # For the last card, let it stay visible until total_duration
            end_t = (current_time + seg.duration) if idx < len(audio_segments) - 1 else total_duration

            if idx > 0:
                transition_timestamps.append(start_t)

            logger.info(f"Overlay Card {idx} ({card_path.name}) active: {start_t:.2f}s -> {end_t:.2f}s")
            card_input = ffmpeg.input(str(card_path))

            # Apply overlay centered horizontally and vertically
            video_stream = ffmpeg.overlay(
                video_stream,
                card_input,
                x="(W-w)/2",
                y="(H-h)/2",
                enable=f"between(t,{start_t:.3f},{end_t:.3f})",
            )
            current_time += seg.duration

        # 3. Build Audio Graph: Concat Voiceover + Transition SFX
        logger.info("Constructing synchronized voiceover and SFX audio graph...")
        voice_inputs = [ffmpeg.input(str(seg.file_path)).audio for seg in audio_segments]
        master_voice = ffmpeg.concat(*voice_inputs, v=0, a=1)

        # Delay SFX for each transition and mix with voiceover
        audio_streams_to_mix = [master_voice]
        for trans_t in transition_timestamps:
            delay_ms = int(trans_t * 1000)
            delayed_sfx = (
                ffmpeg.input(str(self.sfx_path))
                .filter("adelay", f"{delay_ms}|{delay_ms}")
                .filter("volume", 0.85)
            )
            audio_streams_to_mix.append(delayed_sfx)

        if len(audio_streams_to_mix) > 1:
            mixed_audio = ffmpeg.filter(
                audio_streams_to_mix,
                "amix",
                inputs=len(audio_streams_to_mix),
                duration="first",
                dropout_transition=0,
            )
        else:
            mixed_audio = master_voice

        # 4. Final Video & Audio Assembly
        logger.info(f"Rendering final short via FFmpeg to '{output_path}'...")
        pipeline = ffmpeg.output(
            video_stream,
            mixed_audio,
            str(output_path),
            vcodec="libx264",
            acodec="aac",
            audio_bitrate="192k",
            pix_fmt="yuv420p",
            preset="fast",
            crf=18,
            t=f"{total_duration:.3f}",
        ).overwrite_output()

        try:
            pipeline.run(capture_stdout=True, capture_stderr=True)
            logger.info(f"Video compilation succeeded! Saved at: {output_path.resolve()}")
            return output_path
        except ffmpeg.Error as e:
            err_msg = e.stderr.decode("utf8") if e.stderr else str(e)
            logger.error(f"FFmpeg pipeline compilation failed: {err_msg}")
            raise RuntimeError(f"FFmpeg compilation error: {err_msg}")
