from __future__ import annotations

import re
from typing import Any

_POST_ID_RE = re.compile(r"/status/(\d+)")
_METRIC_RE = re.compile(r"([\d,.]+)\s*([KMB])?", re.IGNORECASE)

EXTRACT_TWEETS_JS = r"""
const articles = Array.from(document.querySelectorAll('article[data-testid="tweet"]'));
return articles.map((article) => {
  const permalink = article.querySelector('a[href*="/status/"]');
  const timeNode = article.querySelector('time[datetime]');
  const textNode = article.querySelector('div[data-testid="tweetText"]');
  const userLink = article.querySelector('div[data-testid="User-Name"] a[href^="/"]');
  const verified = Boolean(
    article.querySelector('svg[aria-label*="Verified"], svg[data-testid="icon-verified"]')
  );
  const metric = (testId) => {
    const node = article.querySelector(`button[data-testid="${testId}"]`);
    return node ? (node.getAttribute('aria-label') || node.innerText || '') : '';
  };
  const urls = Array.from(textNode ? textNode.querySelectorAll('a[href]') : []).map((node) => ({
    url: node.getAttribute('href') || '',
    expanded_url: node.getAttribute('href') || '',
  }));
  const cardLink = article.querySelector('a[href^="http"]:not([href*="x.com"]):not([href*="twitter.com"])');
  if (cardLink) {
    urls.push({
      url: cardLink.getAttribute('href') || '',
      expanded_url: cardLink.getAttribute('href') || '',
    });
  }
  const hashtags = Array.from(textNode ? textNode.querySelectorAll('a[href^="/hashtag/"]') : [])
    .map((node) => (node.textContent || '').replace(/^#/, '').trim())
    .filter(Boolean);
  const mentions = Array.from(textNode ? textNode.querySelectorAll('a[href^="/"]') : [])
    .map((node) => {
      const href = node.getAttribute('href') || '';
      if (!href.startsWith('/') || href.includes('/status/') || href.startsWith('/hashtag/')) {
        return '';
      }
      return href.replace(/^\//, '').split('/')[0];
    })
    .filter(Boolean);
  const quoted = article.querySelector('div[role="link"] a[href*="/status/"]');
  return {
    post_id: permalink ? (permalink.getAttribute('href') || '').split('/status/').pop().split('?')[0] : '',
    permalink: permalink ? permalink.getAttribute('href') || '' : '',
    created_at: timeNode ? timeNode.getAttribute('datetime') || '' : '',
    text: textNode ? textNode.innerText || '' : '',
    lang: textNode ? textNode.getAttribute('lang') || 'und' : 'und',
    username: userLink ? (userLink.getAttribute('href') || '').replace(/^\//, '').split('/')[0] : '',
    display_name: article.querySelector('div[data-testid="User-Name"] span')?.innerText || '',
    verified,
    reply_label: metric('reply'),
    retweet_label: metric('retweet'),
    like_label: metric('like'),
    impression_label: metric('app-text-transition-container') || '',
    urls,
    hashtags,
    mentions,
    quoted_post_id: quoted ? (quoted.getAttribute('href') || '').split('/status/').pop().split('?')[0] : '',
    quoted_text: quoted ? (quoted.closest('div[role="link"]')?.innerText || '') : '',
  };
});
"""


def parse_metric_label(label: str) -> int:
    if not label:
        return 0
    match = _METRIC_RE.search(label.replace(",", ""))
    if not match:
        digits = re.sub(r"[^\d]", "", label)
        return int(digits) if digits else 0
    value = float(match.group(1))
    suffix = (match.group(2) or "").upper()
    multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(suffix, 1)
    return int(value * multiplier)


def extract_post_id(raw: dict[str, Any]) -> str | None:
    post_id = str(raw.get("post_id", "")).strip()
    if post_id.isdigit():
        return post_id
    permalink = str(raw.get("permalink", ""))
    match = _POST_ID_RE.search(permalink)
    return match.group(1) if match else None


def build_post(raw: dict[str, Any]) -> dict[str, Any] | None:
    post_id = extract_post_id(raw)
    text = str(raw.get("text", "")).strip()
    if not post_id or not text:
        return None

    entities: dict[str, Any] = {
        "urls": [
            {"url": str(item.get("url", "")), "expanded_url": str(item.get("expanded_url", ""))}
            for item in raw.get("urls", [])
            if isinstance(item, dict) and (item.get("url") or item.get("expanded_url"))
        ],
        "hashtags": [
            {"tag": str(tag)}
            for tag in raw.get("hashtags", [])
            if isinstance(tag, str) and tag
        ],
        "mentions": [
            {"username": str(handle).lstrip("@")}
            for handle in raw.get("mentions", [])
            if isinstance(handle, str) and handle
        ],
    }
    public_metrics = {
        "reply_count": parse_metric_label(str(raw.get("reply_label", ""))),
        "retweet_count": parse_metric_label(str(raw.get("retweet_label", ""))),
        "quote_count": 0,
        "like_count": parse_metric_label(str(raw.get("like_label", ""))),
        "bookmark_count": 0,
        "impression_count": parse_metric_label(str(raw.get("impression_label", ""))),
    }
    referenced_tweets: list[dict[str, str]] = []
    referenced_posts: dict[str, dict[str, Any]] = {}
    quoted_post_id = str(raw.get("quoted_post_id", "")).strip()
    quoted_text = str(raw.get("quoted_text", "")).strip()
    if quoted_post_id.isdigit():
        referenced_tweets.append({"type": "quoted", "id": quoted_post_id})
        if quoted_text:
            referenced_posts[quoted_post_id] = {"id": quoted_post_id, "text": quoted_text}

    return {
        "id": post_id,
        "text": text,
        "author_id": "",
        "conversation_id": "",
        "created_at": str(raw.get("created_at", "")) or None,
        "lang": str(raw.get("lang", "und")) or "und",
        "entities": entities,
        "public_metrics": public_metrics,
        "referenced_tweets": referenced_tweets,
        "_referenced_posts": referenced_posts,
    }


def build_author(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "",
        "username": str(raw.get("username", "")).lstrip("@"),
        "name": str(raw.get("display_name", "")),
        "verified": bool(raw.get("verified")),
        "protected": False,
    }
