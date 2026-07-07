from __future__ import annotations

from dataclasses import dataclass
from typing import List

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None


@dataclass
class SearchResult:
    """
    Search result.
    """
    title: str
    url: str
    snippet: str
    source: str


class WebSearcher:
    """
    Web search interface.
    """

    async def search(self, query: str, num_results: int = 5) -> List[SearchResult]:
        """
        Performs a search by query.
        """
        raise NotImplementedError


class DuckDuckGoSearcher(WebSearcher):
    """
    Real search via DuckDuckGo (free, no API key).
    """

    def __init__(self):
        self._ddgs = DDGS() if DDGS else None

    async def search(self, query: str, num_results: int = 5) -> List[SearchResult]:
        if self._ddgs is None:
            return [SearchResult(
                title="DuckDuckGo not installed",
                url="https://pypi.org/project/duckduckgo-search/",
                snippet="Install with: pip install duckduckgo-search",
                source="Error"
            )]

        try:
            results = self._ddgs.text(query, max_results=num_results)
            return [
                SearchResult(
                    title=r.get('title', ''),
                    url=r.get('href', ''),
                    snippet=r.get('body', ''),
                    source="DuckDuckGo"
                )
                for r in results
            ]
        except Exception as e:
            return [SearchResult(
                title=f"Search error: {type(e).__name__}",
                url="",
                snippet=str(e),
                source="Error"
            )]


class MockWebSearcher(WebSearcher):
    """
    Stub for testing.
    """

    async def search(self, query: str, num_results: int = 5) -> List[SearchResult]:
        return [
            SearchResult(
                title=f"Result for query: {query}",
                url="https://example.com",
                snippet="This is an example search description.",
                source="Mock Search"
            )
        ]
