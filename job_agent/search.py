"""Public-only general web search; it sends no profile or CV data."""
from __future__ import annotations

import html
import re
from urllib.parse import quote_plus
from urllib.request import Request, urlopen


class SearchProviderChallengeError(RuntimeError):
    """The public provider returned a bot/challenge response instead of results."""


def public_search(query: str) -> list[dict]:
    request = Request("https://html.duckduckgo.com/html/?q=" + quote_plus(query), headers={"User-Agent": "Mozilla/5.0 JobSearchingAgent/0.1"})
    with urlopen(request, timeout=15) as response:
        page = response.read().decode("utf-8", "replace")
    lowered = page.lower()
    challenge_markers = ("captcha", "unusual traffic", "automated queries", "bot challenge", "anomaly")
    if any(marker in lowered for marker in challenge_markers):
        raise SearchProviderChallengeError("The public search provider returned a challenge or block.")
    results = []
    for url, title, snippet in re.findall(r'nofollow" class="result__a" href="(.*?)">(.*?)</a>.*?result__snippet">(.*?)</a>', page, re.S):
        results.append({"title": re.sub("<.*?>", "", html.unescape(title)).strip(), "description": re.sub("<.*?>", "", html.unescape(snippet)).strip(), "source_url": html.unescape(url), "source": "web search"})
    return results
