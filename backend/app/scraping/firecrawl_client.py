"""Cliente fino sobre a API de busca + extração da Firecrawl.

Docs: https://docs.firecrawl.dev/api-reference/endpoint/search
Um único POST /v1/search com `scrapeOptions` já devolve título, url e o
conteúdo (markdown) de cada resultado raspado — é por isso que escolhemos a
Firecrawl em vez de Tavily (só busca) + um scraper separado.

Atenção: nomes de campo na resposta de APIs de terceiros mudam com o tempo.
O parsing abaixo é defensivo (tenta algumas chaves alternativas), mas vale
conferir contra a doc atual da Firecrawl se algo vier vazio.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class FirecrawlError(RuntimeError):
    pass


@dataclass
class SearchResult:
    url: str
    title: str = ""
    description: str = ""
    markdown: str = ""
    image_url: Optional[str] = None
    raw: dict = field(default_factory=dict)


@dataclass
class SearchResponse:
    query: str
    results: list[SearchResult]
    credits_used: float


class FirecrawlClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 45.0,
        country: Optional[str] = None,
        location: Optional[str] = None,
    ):
        settings = get_settings()
        self.api_key = api_key or settings.firecrawl_api_key
        self.base_url = (base_url or settings.firecrawl_base_url).rstrip("/")
        self.timeout = timeout
        # Geo-bias dos resultados — prioriza lojas brasileiras/da região
        # configurada em vez de restringir a busca a domínios fixos.
        self.country = country or settings.firecrawl_search_country
        self.location = location or settings.firecrawl_search_location

    def _headers(self) -> dict:
        if not self.api_key:
            raise FirecrawlError(
                "FIRECRAWL_API_KEY não configurada. Preencha no .env antes de "
                "rodar buscas reais (veja README)."
            )
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def search(self, query: str, scrape_top_n: int = 3) -> SearchResponse:
        """Busca `query` e raspa o conteúdo dos `scrape_top_n` primeiros resultados.

        Custo aproximado usado no orçamento (ver README/plano): 2 créditos
        "base" da chamada de busca + 1 crédito por página raspada.
        """
        payload: dict[str, Any] = {"query": query, "limit": max(1, scrape_top_n)}
        if self.country:
            payload["country"] = self.country
        if self.location:
            payload["location"] = self.location
        if scrape_top_n > 0:
            payload["scrapeOptions"] = {"formats": ["markdown"], "onlyMainContent": True}

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(f"{self.base_url}/search", json=payload, headers=self._headers())

        if resp.status_code != 200:
            raise FirecrawlError(f"Firecrawl retornou {resp.status_code}: {resp.text[:500]}")

        body = resp.json()
        if body.get("success") is False:
            raise FirecrawlError(f"Firecrawl reportou falha: {body}")

        raw_results = body.get("data", []) or []
        results = [self._parse_result(item) for item in raw_results]
        credits_used = self._extract_or_estimate_credits(body, len(raw_results), scrape_top_n)

        return SearchResponse(query=query, results=results, credits_used=credits_used)

    @staticmethod
    def _parse_result(item: dict) -> SearchResult:
        metadata = item.get("metadata") or {}
        image_url = (
            item.get("image")
            or metadata.get("ogImage")
            or metadata.get("image")
        )
        return SearchResult(
            url=item.get("url", ""),
            title=item.get("title") or metadata.get("title", ""),
            description=item.get("description") or metadata.get("description", ""),
            markdown=item.get("markdown", "") or "",
            image_url=image_url,
            raw=item,
        )

    @staticmethod
    def _extract_or_estimate_credits(body: dict, results_count: int, scrape_top_n: int) -> float:
        # Se a API reportar o uso real de créditos, confiamos nela.
        for key in ("creditsUsed", "credits_used", "creditsConsumed"):
            if key in body:
                try:
                    return float(body[key])
                except (TypeError, ValueError):
                    pass
        # Caso contrário, usamos a mesma fórmula de estimativa do orçamento:
        # 2 créditos "base" por chamada de busca + 1 crédito por página raspada.
        return 2.0 + min(results_count, scrape_top_n)
