#!/usr/bin/env python3
"""Rewrite legacy WordPress code blocks and attach related media."""

import base64
import os
import re
import sys
from html import escape, unescape

import requests

from binlib import (
    append_enrichment_to_post,
    search_image_url_unsplash,
    search_youtube_video,
    upload_image_to_wordpress,
    wordpress_openai,
)

WP_SITE = os.getenv("WORDPRESS_URL", "https://www.fio.ie") + "/wp-json/wp/v2/"
USERNAME = os.getenv("WORDPRESS_USERNAME")
APPLICATION = os.getenv("WORDPRESS_APPLICATION")
UNSPLASH_API_KEY = os.getenv("UNSPLASH_API_KEY")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")


def search_image(query: str, api_key: str | None) -> str | None:
    """Look up a landscape Unsplash image. Kept for callers of the old name."""
    return search_image_url_unsplash(query, api_key)


def get_auth_header() -> dict[str, str]:
    """Return the basic-auth header used for WordPress requests."""
    token = base64.b64encode(f"{USERNAME}:{APPLICATION}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
    }


def convert_pre_tags(html: str) -> str:
    """Turn legacy ``<pre class="lang:...">`` blocks into Prism code blocks."""
    pattern = r'<pre\s+[^>]*class=["\']lang:(\w+)["\'][^>]*>(.*?)</pre>'

    def repl(match: re.Match[str]) -> str:
        lang = match.group(1).lower()
        code = match.group(2).strip()
        return f'<pre><code class="language-{lang}">{escape(code)}</code></pre>'

    return re.sub(pattern, repl, html, flags=re.DOTALL | re.IGNORECASE)


def process_post(post: dict) -> dict:
    """Decode entities and convert legacy code blocks on one post."""
    content = post.get("content", {}).get("rendered", "")
    content = unescape(content)
    content = convert_pre_tags(content)
    post["content"] = {"raw": content}
    return post


def _media_suggestions(ai_response: str) -> tuple[str | None, list[str]]:
    """Parse ``image_idea`` and ``youtube_topics`` lines from the model reply."""
    image_idea = None
    youtube_topics: list[str] = []
    for line in ai_response.splitlines():
        if line.lower().startswith("image_idea:"):
            image_idea = line.split(":", 1)[1].strip()
        elif line.lower().startswith("youtube_topics:"):
            youtube_topics = [item.strip() for item in line.split(":", 1)[1].split(",")]
    return image_idea, youtube_topics


def _featured_image(
    title: str,
    image_idea: str | None,
    unsplash_api_key: str | None,
) -> str | None:
    """Upload an Unsplash image and return its WordPress URL."""
    if not image_idea:
        return None
    unsplash_url = search_image(image_idea, unsplash_api_key)
    if not unsplash_url:
        return None
    image_name = title.replace(" ", "_") + ".jpg"
    return upload_image_to_wordpress(
        unsplash_url,
        image_name,
        f"{WP_SITE}media",
        USERNAME,
        APPLICATION,
    )


def _first_video(topics: list[str], youtube_api_key: str | None) -> str | None:
    """Return the first YouTube embed URL that resolves."""
    for topic in topics:
        video_url = search_youtube_video(topic, youtube_api_key)
        if video_url:
            return video_url
    return None


def _set_featured_media(post: dict, featured_image_url: str | None, title: str) -> None:
    """Upload the featured image again and store its media id on ``post``."""
    if not featured_image_url:
        return
    img_data = requests.get(featured_image_url, timeout=60).content
    headers = get_auth_header()
    headers.update(
        {
            "Content-Disposition": f"attachment; filename={title}.jpg",
            "Content-Type": "image/jpeg",
        }
    )
    media_response = requests.post(
        f"{WP_SITE}media",
        headers=headers,
        data=img_data,
        timeout=60,
    )
    if media_response.status_code == 201:
        media_id = media_response.json().get("id")
        post["featured_media"] = media_id


def enrich_post_with_ai(
    post: dict,
    ai_client,
    unsplash_api_key: str | None,
    youtube_api_key: str | None,
) -> dict:
    """Ask OpenAI for media ideas and attach an image and a video."""
    title = post["title"]["rendered"]
    content = post["content"]["raw"]
    prompt = """You're helping enrich a blog post with multimedia.\u0020
Based on the following blog content, suggest:
1. image_idea: A vivid description of a related image that could visually represent this post.
2. youtube_topics: Two short YouTube video topics relevant to the post's content.

Return in this format:
image_idea: ...
youtube_topics: topic for first video, topic for second video
"""
    image_idea, youtube_topics = _media_suggestions(
        ai_client.improve_text(prompt, content),
    )
    featured_image_url = _featured_image(title, image_idea, unsplash_api_key)
    enriched_content = append_enrichment_to_post(
        content,
        _first_video(youtube_topics, youtube_api_key),
    )
    post["content"] = {"raw": enriched_content}
    _set_featured_media(post, featured_image_url, title)
    return post


def update_posts(items, ai_provider, post_type: str) -> None:
    """Rewrite and save each post or page in ``items``."""
    for post in items:
        updated_content = process_post(post)
        enriched_post = enrich_post_with_ai(
            updated_content,
            ai_provider,
            UNSPLASH_API_KEY,
            YOUTUBE_API_KEY,
        )
        payload = {"content": enriched_post["content"]["raw"]}
        if "featured_media" in enriched_post:
            payload["featured_media"] = enriched_post["featured_media"]
        update_url = f"{WP_SITE}{post_type}/{post['id']}"
        result = requests.put(
            update_url,
            json=payload,
            headers=get_auth_header(),
            timeout=60,
        )
        title = post["title"]["rendered"]
        if result.status_code == 200:
            print(f"✅ Successfully updated {post_type} ID {post['id']}: {title}")
        else:
            print(f"❌ Failed to update {post_type} ID {post['id']}: {result.text}")


def update_content(post_type: str) -> None:
    """Fetch one page of ``post_type`` and update those items."""
    ai_provider = wordpress_openai()
    page = 1
    while True:
        url = f"{WP_SITE}{post_type}?per_page=100&page={page}"
        response = requests.get(url, headers=get_auth_header(), timeout=60)
        if response.status_code != 200:
            print(
                f"⚠️ Failed to fetch {post_type} (page {page}): {response.status_code}",
            )
            break
        items = response.json()
        if not items:
            break
        update_posts(items, ai_provider, post_type)
        page += 1
        return


if __name__ == "__main__":
    update_content("posts")
    sys.exit(0)
