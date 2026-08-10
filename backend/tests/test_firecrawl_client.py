import httpx
import pytest

from app.scraping.firecrawl_client import FirecrawlClient, FirecrawlError

FAKE_RESPONSE = {
    "success": True,
    "data": [
        {
            "url": "https://loja-exemplo.com.br/porcelanato-80x80",
            "title": "Porcelanato 80x80 em promoção",
            "description": "Porcelanato acetinado com desconto",
            "markdown": "# Porcelanato 80x80\nPreço: R$ 89,90/m²",
            "metadata": {"ogImage": "https://loja-exemplo.com.br/img.jpg"},
        }
    ],
}


def _mock_transport(expected_url_suffix: str, response_json: dict, status_code: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(expected_url_suffix)
        assert request.headers["Authorization"] == "Bearer fake-key"
        return httpx.Response(status_code, json=response_json)

    return httpx.MockTransport(handler)


def test_search_parses_results_and_estimates_credits(monkeypatch):
    client = FirecrawlClient(api_key="fake-key", base_url="https://api.firecrawl.dev/v1")

    def fake_post(self, url, json=None, headers=None, **kwargs):
        assert headers["Authorization"] == "Bearer fake-key"
        assert json["query"] == "porcelanato promoção"
        return httpx.Response(200, json=FAKE_RESPONSE, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    result = client.search("porcelanato promoção", scrape_top_n=3)

    assert result.query == "porcelanato promoção"
    assert len(result.results) == 1
    item = result.results[0]
    assert item.url == "https://loja-exemplo.com.br/porcelanato-80x80"
    assert "R$ 89,90" in item.markdown
    assert item.image_url == "https://loja-exemplo.com.br/img.jpg"
    # 2 (base) + min(1 resultado, 3 scrape_top_n) = 3
    assert result.credits_used == 3.0


def test_search_sends_geo_bias_params_by_default(monkeypatch):
    client = FirecrawlClient(api_key="fake-key")

    captured = {}

    def fake_post(self, url, json=None, headers=None, **kwargs):
        captured.update(json)
        return httpx.Response(200, json=FAKE_RESPONSE, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    client.search("porcelanato promoção", scrape_top_n=3)

    assert captured["country"] == "BR"
    assert captured["location"] == "Rio de Janeiro, Rio de Janeiro, Brazil"


def test_search_geo_bias_is_configurable_per_client(monkeypatch):
    client = FirecrawlClient(api_key="fake-key", country="BR", location="Macaé, Rio de Janeiro, Brazil")

    captured = {}

    def fake_post(self, url, json=None, headers=None, **kwargs):
        captured.update(json)
        return httpx.Response(200, json=FAKE_RESPONSE, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    client.search("porcelanato promoção", scrape_top_n=3)

    assert captured["location"] == "Macaé, Rio de Janeiro, Brazil"


def test_search_raises_without_api_key():
    client = FirecrawlClient(api_key="")
    with pytest.raises(FirecrawlError, match="FIRECRAWL_API_KEY"):
        client.search("qualquer coisa")


def test_search_raises_on_http_error(monkeypatch):
    client = FirecrawlClient(api_key="fake-key")

    def fake_post(self, url, json=None, headers=None, **kwargs):
        return httpx.Response(402, text="payment required", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    with pytest.raises(FirecrawlError, match="402"):
        client.search("porcelanato promoção")
