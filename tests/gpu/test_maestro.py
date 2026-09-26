"""The real Maestro server of the image on a GPU, below the deployment's prefix."""
from urllib.parse import urlparse

import requests
from playwright.sync_api import Page

from conftest import PREFIX, PROXY_URL

APP = PROXY_URL + PREFIX + "/"


def test_gpu_detected():
    answer = requests.get(APP + "api/v1/system-detect", timeout=30).json()
    assert answer["hardware"]["cuda_available"] is True, answer


def test_models_listed():
    response = requests.get(APP + "api/v1/models", timeout=60)
    assert response.status_code == 200
    assert response.json()


def test_api_docs_below_prefix():
    response = requests.get(APP + "docs", timeout=30)
    assert response.status_code == 200
    assert "swagger" in response.text.lower()


def test_classic_interface_below_prefix(page: Page):
    requested = []
    page.on("request", lambda request: requested.append(request.url))
    page.goto(APP + "classic")
    assert page.url == APP + "classic/"
    page.wait_for_selector("gradio-app", timeout=120000)
    page.wait_for_load_state("networkidle")
    own = [url for url in requested if urlparse(url).netloc == urlparse(PROXY_URL).netloc]
    outside = [url for url in own if not urlparse(url).path.startswith(PREFIX + "/")]
    assert not outside, f"requests left the prefix: {outside}"


def test_interface_below_prefix(page: Page):
    requested = []
    failed = []
    page.on("request", lambda request: requested.append(request.url))
    page.on("response", lambda response: failed.append((response.url, response.status)) if response.status >= 400 else None)
    page.goto(APP)
    page.wait_for_function("document.getElementById('root').children.length > 0", timeout=60000)
    page.wait_for_load_state("networkidle")
    assert "Maestro UI failed to load" not in page.content()
    own = [url for url in requested if urlparse(url).netloc == urlparse(PROXY_URL).netloc]
    outside = [url for url in own if not urlparse(url).path.startswith(PREFIX + "/")]
    assert not outside, f"requests left the prefix: {outside}"
    assert not failed, f"failed requests: {failed}"


def test_maestro_config_applied():
    answer = requests.get(APP + "api/v1/system-config", timeout=30).json()
    assert (answer["video_profile"], answer["image_profile"], answer["vae_config"]) == (4, 4, 3), answer
