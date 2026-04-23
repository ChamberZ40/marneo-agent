# tests/tools/test_web.py
import json
from unittest.mock import patch, MagicMock
from marneo.tools.core.web import web_fetch, web_search


def test_web_fetch_returns_content():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><body><p>Hello world</p></body></html>"
    mock_resp.headers = {"content-type": "text/html"}
    mock_resp.raise_for_status = MagicMock()
    with patch("httpx.get", return_value=mock_resp):
        result = json.loads(web_fetch({"url": "https://example.com"}))
    assert "Hello world" in result.get("content", "")
    assert result.get("url") == "https://example.com"


def test_web_fetch_missing_url():
    result = json.loads(web_fetch({}))
    assert "error" in result


def test_web_fetch_non_http_url_blocked():
    result = json.loads(web_fetch({"url": "file:///etc/passwd"}))
    assert "error" in result


def test_web_search_missing_query():
    result = json.loads(web_search({}))
    assert "error" in result


def test_web_search_returns_gracefully():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "AbstractText": "Python is a programming language.",
        "AbstractURL": "https://python.org",
        "Heading": "Python",
        "RelatedTopics": [],
    }
    with patch("httpx.get", return_value=mock_resp):
        result = json.loads(web_search({"query": "python"}))
    assert "results" in result
    assert len(result["results"]) >= 1
    assert result["results"][0]["content"] == "Python is a programming language."
