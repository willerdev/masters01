import base64

import httpx

from app.services.ai_service import create_image, describe_image

KEY = "sk-test-openai"


def _response(payload, status=200):
    class Response:
        status_code = status

        def json(self):
            return payload

    return Response()


def test_describe_image_uses_the_official_host_and_gpt4o(monkeypatch):
    seen = {}

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            seen["url"] = url
            seen["model"] = json["model"]
            assert headers["Authorization"] == f"Bearer {KEY}"
            assert json["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
            return _response({"choices": [{"message": {"content": "Volatility 75 is falling."}}]})

    monkeypatch.setattr(httpx, "Client", Client)
    assert describe_image(KEY, b"jpeg-bytes", "image/jpeg", "What is this?") == "Volatility 75 is falling."
    assert seen["url"] == "https://api.openai.com/v1/chat/completions"
    assert seen["model"] == "gpt-4o"
    assert KEY not in seen["url"]


def test_create_image_returns_png_bytes(monkeypatch):
    encoded = base64.b64encode(b"png-bytes").decode("ascii")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            assert url == "https://api.openai.com/v1/images/generations"
            assert json["model"] == "gpt-image-1"
            assert KEY not in url
            return _response({"data": [{"b64_json": encoded}]})

    monkeypatch.setattr(httpx, "Client", Client)
    assert create_image(KEY, "a chart of the last hour") == b"png-bytes"
