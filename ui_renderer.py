import asyncio
import os
from pathlib import Path
from typing import Dict, Any, List
from jinja2 import Template
from playwright.async_api import async_playwright, Browser, Page

from logger import get_logger
from llm_processor import ProcessedVideoContent, SelectedComment

logger = get_logger("UIRenderer")

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  * {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }
  body {
    background-color: transparent;
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  
  .card {
    width: 880px;
    background: rgba(18, 22, 28, 0.94);
    backdrop-filter: blur(28px);
    -webkit-backdrop-filter: blur(28px);
    border: 1.5px solid rgba(255, 255, 255, 0.14);
    border-radius: 32px;
    padding: 38px 42px;
    box-shadow: 0 30px 60px rgba(0, 0, 0, 0.65), 0 0 1px rgba(255, 255, 255, 0.2);
    color: #ffffff;
    display: flex;
    flex-direction: column;
    gap: 24px;
  }

  /* Header */
  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .user-info {
    display: flex;
    align-items: center;
    gap: 16px;
  }
  .avatar {
    width: 60px;
    height: 60px;
    border-radius: 50%;
    background: {{ avatar_gradient }};
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 26px;
    font-weight: 700;
    color: #ffffff;
    border: 2px solid rgba(255, 255, 255, 0.15);
  }
  .names {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .username-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .display-name {
    font-size: 26px;
    font-weight: 700;
    color: #f8fafc;
  }
  .badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: #38bdf8;
  }
  .handle {
    font-size: 20px;
    color: #94a3b8;
    font-weight: 500;
  }
  .time-badge {
    background: rgba(255, 255, 255, 0.08);
    border-radius: 20px;
    padding: 6px 16px;
    font-size: 18px;
    color: #94a3b8;
    font-weight: 600;
  }

  /* Subreddit Badge */
  .sub-tag {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: #ff4500;
    color: #ffffff;
    font-size: 19px;
    font-weight: 700;
    padding: 6px 16px;
    border-radius: 20px;
    letter-spacing: 0.5px;
  }

  /* Content */
  .content {
    font-size: 32px;
    line-height: 1.45;
    color: #f1f5f9;
    font-weight: 500;
    word-break: break-word;
    letter-spacing: -0.01em;
  }
  .title-content {
    font-size: 38px;
    line-height: 1.35;
    font-weight: 800;
    color: #ffffff;
    letter-spacing: -0.02em;
  }

  /* Footer Action Bar */
  .card-footer {
    display: flex;
    align-items: center;
    gap: 28px;
    padding-top: 10px;
    border-top: 1px solid rgba(255, 255, 255, 0.08);
  }
  .pill {
    display: flex;
    align-items: center;
    gap: 10px;
    background: rgba(255, 255, 255, 0.06);
    padding: 10px 20px;
    border-radius: 24px;
    font-size: 22px;
    font-weight: 700;
    color: #cbd5e1;
  }
  .upvote-icon {
    color: #ff4500;
  }
</style>
</head>
<body>
  <div class="card" id="target-card">
    <div class="card-header">
      <div class="user-info">
        <div class="avatar">{{ initial }}</div>
        <div class="names">
          <div class="username-row">
            <span class="display-name">{{ author }}</span>
            <span class="badge">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
              </svg>
            </span>
          </div>
          <span class="handle">@{{ author|lower }}</span>
        </div>
      </div>
      
      {% if is_title %}
        <div class="sub-tag">r/{{ subreddit }}</div>
      {% else %}
        <div class="time-badge">Top Comment</div>
      {% endif %}
    </div>

    <div class="content {% if is_title %}title-content{% endif %}">
      {{ content }}
    </div>

    <div class="card-footer">
      <div class="pill">
        <svg class="upvote-icon" width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 4L4 12h5v8h6v-8h5L12 4z"/>
        </svg>
        <span>{{ score }}</span>
      </div>
      <div class="pill">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="#94a3b8">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
        </svg>
        <span>Share</span>
      </div>
    </div>
  </div>
</body>
</html>
"""

GRADIENTS = [
    "linear-gradient(135deg, #6366f1, #a855f7)",
    "linear-gradient(135deg, #ec4899, #f43f5e)",
    "linear-gradient(135deg, #06b6d4, #3b82f6)",
    "linear-gradient(135deg, #10b981, #059669)",
    "linear-gradient(135deg, #f59e0b, #ef4444)",
]


class UIRenderer:
    """Renders HTML/CSS comment and title cards to transparent PNGs using Playwright."""

    def __init__(self, output_dir: str = "output/cards"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.template = Template(HTML_TEMPLATE)

    async def _render_card_image(
        self,
        page: Page,
        html_content: str,
        output_file: Path,
    ) -> Path:
        """Helper to set HTML content and take element screenshot with transparent background."""
        await page.set_content(html_content, wait_until="load")
        card = page.locator("#target-card")
        await card.screenshot(path=str(output_file), omit_background=True)
        return output_file

    async def generate_cards(
        self,
        processed_data: ProcessedVideoContent,
        raw_title: str,
        subreddit: str,
        author: str,
        post_score: int,
    ) -> List[Path]:
        """
        Renders the title card and 4 comment cards, returning a list of saved PNG paths.
        Uses headless Chromium with omit_background=True.
        """
        logger.info("Launching Playwright async browser for UI rendering...")
        rendered_images: List[Path] = []

        async with async_playwright() as p:
            browser: Browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"],
            )
            # High device scale factor ensures crisp, retina-grade text rasterization
            page: Page = await browser.new_page(
                viewport={"width": 1080, "height": 1920},
                device_scale_factor=2,
            )

            # 1. Render Title Card
            logger.info("Rendering Title card...")
            title_score_str = f"{post_score/1000:.1f}k" if post_score >= 1000 else str(post_score)
            title_html = self.template.render(
                is_title=True,
                author=author,
                initial=author[0].upper() if author else "R",
                avatar_gradient=GRADIENTS[0],
                subreddit=subreddit,
                content=raw_title,
                score=title_score_str,
            )
            title_card_path = self.output_dir / "card_0_title.png"
            await self._render_card_image(page, title_html, title_card_path)
            rendered_images.append(title_card_path)

            # 2. Render Comment Cards
            for idx, comment in enumerate(processed_data.comments, start=1):
                logger.info(f"Rendering Comment card #{idx} (u/{comment.original_author})...")
                comment_html = self.template.render(
                    is_title=False,
                    author=comment.original_author,
                    initial=comment.original_author[0].upper() if comment.original_author else "U",
                    avatar_gradient=GRADIENTS[idx % len(GRADIENTS)],
                    subreddit=subreddit,
                    content=comment.display_text,
                    score=comment.score_display,
                )
                comment_card_path = self.output_dir / f"card_{idx}_comment.png"
                await self._render_card_image(page, comment_html, comment_card_path)
                rendered_images.append(comment_card_path)

            await browser.close()

        logger.info(f"All {len(rendered_images)} UI cards successfully rendered to PNG.")
        return rendered_images
