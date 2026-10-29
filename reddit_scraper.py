import os
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
import praw
from praw.models import MoreComments, Comment, Submission

from logger import get_logger

logger = get_logger("RedditScraper")


class RedditChildReply(BaseModel):
    """Data model representing a direct reply to a comment."""
    id: str
    author: str
    score: int
    body: str


class RedditComment(BaseModel):
    """Data model representing a top-level comment and its immediate replies."""
    id: str
    author: str
    score: int
    body: str
    child_replies: List[RedditChildReply] = Field(default_factory=list)


class RedditPost(BaseModel):
    """Data model representing a Reddit submission with scraped comments."""
    id: str
    subreddit: str
    title: str
    author: str
    score: int
    url: str
    num_comments: int
    comments: List[RedditComment] = Field(default_factory=list)


class RedditScraper:
    """Service to scrape high-engagement posts and comment threads using PRAW."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        user_agent: Optional[str] = None,
    ):
        self.client_id = client_id or os.getenv("REDDIT_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("REDDIT_CLIENT_SECRET")
        self.user_agent = user_agent or os.getenv("REDDIT_USER_AGENT", "ViralShortsBot/1.0")

        if not self.client_id or not self.client_secret:
            raise ValueError(
                "Reddit API credentials missing. Provide REDDIT_CLIENT_ID and "
                "REDDIT_CLIENT_SECRET via environment variables or constructor."
            )

        logger.info("Initializing PRAW Reddit client...")
        self.reddit = praw.Reddit(
            client_id=self.client_id,
            client_secret=self.client_secret,
            user_agent=self.user_agent,
        )

    def fetch_top_post(
        self,
        subreddit_name: str = "AskReddit",
        time_filter: str = "day",
        comment_limit: int = 15,
        max_child_replies: int = 2,
    ) -> RedditPost:
        """
        Fetches the top post of the specified time period from a subreddit along with
        its top comments and up to max_child_replies per comment.

        :param subreddit_name: Subreddit name (e.g., 'AskReddit', 'UnethicalLifeProTips')
        :param time_filter: One of 'all', 'day', 'hour', 'month', 'week', 'year'
        :param comment_limit: Number of top-level comments to fetch (default: 15)
        :param max_child_replies: Maximum child replies per top comment (default: 2)
        :return: RedditPost containing post metadata and structured comments
        """
        logger.info(f"Connecting to r/{subreddit_name} to fetch top post ({time_filter})...")
        try:
            subreddit = self.reddit.subreddit(subreddit_name)
            top_submissions = subreddit.top(time_filter=time_filter, limit=1)
            submission: Submission = next(top_submissions, None)
        except Exception as e:
            logger.error(f"Failed to query subreddit r/{subreddit_name}: {e}")
            raise

        if not submission:
            raise RuntimeError(f"No submissions found in r/{subreddit_name} for time_filter='{time_filter}'")

        author_name = submission.author.name if submission.author else "[deleted]"
        logger.info(f"Selected post: '{submission.title}' (ID: {submission.id}, Score: {submission.score})")

        # Resolve comments
        logger.info(f"Loading top {comment_limit} comments and associated child replies...")
        submission.comments.replace_more(limit=0)

        structured_comments: List[RedditComment] = []
        for raw_comment in submission.comments[:comment_limit]:
            if isinstance(raw_comment, MoreComments):
                continue

            comment_author = raw_comment.author.name if raw_comment.author else "[deleted]"
            comment_body = raw_comment.body.strip()

            # Ignore empty or removed comments
            if not comment_body or comment_body in ["[deleted]", "[removed]"]:
                continue

            child_replies: List[RedditChildReply] = []
            for reply in raw_comment.replies[:max_child_replies]:
                if isinstance(reply, MoreComments):
                    continue
                reply_author = reply.author.name if reply.author else "[deleted]"
                reply_body = reply.body.strip()
                if reply_body and reply_body not in ["[deleted]", "[removed]"]:
                    child_replies.append(
                        RedditChildReply(
                            id=reply.id,
                            author=reply_author,
                            score=reply.score,
                            body=reply_body,
                        )
                    )

            structured_comments.append(
                RedditComment(
                    id=raw_comment.id,
                    author=comment_author,
                    score=raw_comment.score,
                    body=comment_body,
                    child_replies=child_replies,
                )
            )

        logger.info(f"Successfully scraped {len(structured_comments)} top-level comments.")
        return RedditPost(
            id=submission.id,
            subreddit=subreddit_name,
            title=submission.title.strip(),
            author=author_name,
            score=submission.score,
            url=submission.url,
            num_comments=submission.num_comments,
            comments=structured_comments,
        )
