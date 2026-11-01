import html
import re
from urllib.parse import quote

import httpx

from app.core.config import Settings


class OpenAccessAdapter:
    """Adapter for querying open-access academic metadata (e.g. Semantic Scholar / OpenAlex).

    Used as an enrichment fallback when Crossref metadata lacks an abstract.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def fetch_abstract(self, doi: str | None = None, title: str | None = None) -> str | None:
        """Attempt to fetch paper abstract from public academic APIs."""
        if not doi and not title:
            return None

        # 1. Try Semantic Scholar with DOI first
        if doi:
            abstract = await self._fetch_semantic_scholar_by_doi(doi)
            if abstract:
                return abstract

        # 2. Try OpenAlex with DOI
        if doi:
            abstract = await self._fetch_openalex_by_doi(doi)
            if abstract:
                return abstract

        # 3. Try Semantic Scholar search by Title
        if title and len(title.strip()) > 10:
            abstract = await self._search_semantic_scholar_by_title(title.strip())
            if abstract:
                return abstract

        return None

    async def _fetch_semantic_scholar_by_doi(self, doi: str) -> str | None:
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{quote(doi, safe='')}"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(url, params={"fields": "abstract"})
                if response.status_code == 200:
                    data = response.json()
                    abstract = data.get("abstract")
                    if isinstance(abstract, str) and len(abstract.strip()) > 20:
                        return self._clean_abstract(abstract)
        except Exception:
            return None
        return None

    async def _search_semantic_scholar_by_title(self, title: str) -> str | None:
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                params: dict[str, str | int] = {
                    "query": title,
                    "limit": 1,
                    "fields": "title,abstract",
                }
                response = await client.get(url, params=params)
                if response.status_code == 200:
                    data = response.json()
                    items = data.get("data", [])
                    if items and isinstance(items[0], dict):
                        abstract = items[0].get("abstract")
                        if isinstance(abstract, str) and len(abstract.strip()) > 20:
                            return self._clean_abstract(abstract)
        except Exception:
            return None
        return None

    async def _fetch_openalex_by_doi(self, doi: str) -> str | None:
        url = f"https://api.openalex.org/works/https://doi.org/{quote(doi, safe='')}"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    inverted = data.get("abstract_inverted_index")
                    if isinstance(inverted, dict):
                        return self._reconstruct_inverted_index(inverted)
        except Exception:
            return None
        return None

    @staticmethod
    def _reconstruct_inverted_index(inverted: dict[str, list[int]]) -> str | None:
        try:
            word_positions: list[tuple[int, str]] = []
            for word, positions in inverted.items():
                for pos in positions:
                    word_positions.append((pos, word))
            word_positions.sort(key=lambda x: x[0])
            result = " ".join(word for _, word in word_positions).strip()
            return result if len(result) > 20 else None
        except Exception:
            return None

    @staticmethod
    def _clean_abstract(text: str) -> str:
        without_tags = re.sub(r"<[^>]+>", " ", text)
        return " ".join(html.unescape(without_tags).split())
