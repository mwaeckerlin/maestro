"""The Maestro interface below a path prefix, through the proxy of the deployment.

The interface is the real build of the image; the backend answers are the
harness's (tests/e2e/harness), because the Maestro server needs a GPU.
"""
from urllib.parse import urlparse

import requests
from playwright.sync_api import Page

from conftest import HARNESS_URL, LOCAL_URL, PREFIX, PROXY_URL

APP = PROXY_URL + PREFIX + "/"


def open_interface(page: Page, url=APP):
    """Load the interface, record every request, wait until React mounted."""
    requested = []
    page.on("request", lambda request: requested.append(request.url))
    responses = {}
    page.on("response", lambda response: responses.__setitem__(response.url, response.status))
    page.goto(url)
    page.wait_for_function("document.getElementById('root') && document.getElementById('root').children.length > 0", timeout=15000)
    page.wait_for_load_state("networkidle")
    return requested, responses


def test_bare_prefix_redirects_to_slash():
    response = requests.get(PROXY_URL + PREFIX, allow_redirects=False, timeout=10)
    assert response.status_code in (301, 308)
    assert response.headers["Location"].endswith(PREFIX + "/")


def test_interface_mounts_below_prefix(page: Page):
    requested, responses = open_interface(page)
    # the watchdog of index.html carries this sentence in its source and shows
    # it only when React has not mounted after 10 seconds
    page.wait_for_timeout(11000)
    assert "Maestro UI failed to load" not in page.locator("body").inner_text()
    own = [url for url in requested if urlparse(url).netloc == urlparse(PROXY_URL).netloc]
    assert own, "the page made no request to its own server"
    outside = [url for url in own if not urlparse(url).path.startswith(PREFIX + "/")]
    assert not outside, f"requests left the prefix: {outside}"


def test_bundle_and_assets_load_below_prefix(page: Page):
    _, responses = open_interface(page)
    assets = {url: status for url, status in responses.items() if "/assets/" in url or url.endswith(".js") or url.endswith(".css")}
    assert assets, "no bundle was loaded"
    failed = {url: status for url, status in assets.items() if status != 200}
    assert not failed, f"assets failed: {failed}"


def test_fetch_of_root_absolute_api_reaches_maestro(page: Page):
    open_interface(page)
    answer = page.evaluate("fetch('/api/v1/e2e/file-url').then(response => response.json())")
    assert answer["root_path"] == PREFIX


def test_fetch_with_request_object_and_url_object(page: Page):
    open_interface(page)
    paths = page.evaluate("""async () => [
        (await fetch(new Request('/api/v1/e2e/file-url')).then(r => r.json())).root_path,
        (await fetch(new URL('/api/v1/e2e/file-url', location.origin)).then(r => r.json())).root_path,
    ]""")
    assert paths == [PREFIX, PREFIX]


def test_server_file_url_loads_as_image(page: Page):
    open_interface(page)
    result = page.evaluate("""async () => {
        const { url } = await fetch('/api/v1/e2e/file-url').then(r => r.json())
        const byProperty = new Image()
        const byAttribute = document.createElement('img')
        document.body.appendChild(byAttribute)
        const loaded = image => new Promise((resolve, reject) => { image.onload = resolve; image.onerror = reject })
        const waits = [loaded(byProperty), loaded(byAttribute)]
        byProperty.src = url
        byAttribute.setAttribute('src', url)
        await Promise.all(waits)
        return [byProperty.src, byProperty.naturalWidth, byAttribute.src, byAttribute.naturalWidth]
    }""")
    expected = PROXY_URL + PREFIX + "/api/v1/e2e/file/probe.png"
    assert result == [expected, 1, expected, 1]


def test_link_and_window_open_keep_prefix(page: Page):
    open_interface(page)
    href = page.evaluate("(() => { const a = document.createElement('a'); a.href = '/api/v1/e2e/file/link.png'; return a.href })()")
    assert href == PROXY_URL + PREFIX + "/api/v1/e2e/file/link.png"
    with page.context.expect_page() as popup:
        page.evaluate("window.open('/api/v1/e2e/file/popup.png')")
    popup.value.wait_for_load_state()
    assert popup.value.url == PROXY_URL + PREFIX + "/api/v1/e2e/file/popup.png"


def test_icon_of_index_html_is_rebased(page: Page):
    open_interface(page)
    href = page.evaluate("document.querySelector('link[rel=icon]').href")
    assert href == PROXY_URL + PREFIX + "/maestro-icon.png"
    assert requests.get(href, timeout=10).status_code == 200


def test_service_worker_registers_below_prefix(page: Page):
    # localhost is a secure context, where the service worker API exists
    open_interface(page, LOCAL_URL + PREFIX + "/")
    scope = page.evaluate("navigator.serviceWorker.register('/maestro-sw.js', { scope: '/' }).then(registration => registration.scope)")
    assert scope == LOCAL_URL + PREFIX + "/"


def test_foreign_and_prefixed_urls_stay_unchanged(page: Page):
    open_interface(page)
    results = page.evaluate(f"""[
        window.__maestroRebase('https://example.org/api/v1/x'),
        window.__maestroRebase('//cdn.example.org/x.js'),
        window.__maestroRebase('{PREFIX}/api/v1/x'),
        window.__maestroRebase('relative/path'),
        window.__maestroRebase('data:image/png;base64,AAAA'),
    ]""")
    assert results == [
        "https://example.org/api/v1/x",
        "//cdn.example.org/x.js",
        f"{PREFIX}/api/v1/x",
        "relative/path",
        "data:image/png;base64,AAAA",
    ]


def test_forwarded_prefix_reaches_the_server():
    requests.get(APP + "api/v1/e2e/file-url", timeout=10)
    seen = requests.get(APP + "api/v1/e2e/seen", timeout=10).json()
    proxied = [entry for entry in seen if entry["path"].endswith("/api/v1/e2e/file-url")]
    assert proxied and proxied[-1]["root_path"] == PREFIX
    assert proxied[-1]["path"] == PREFIX + "/api/v1/e2e/file-url"


def test_classic_redirect_keeps_prefix():
    response = requests.get(APP + "classic", allow_redirects=False, timeout=10)
    assert response.status_code in (302, 307)
    assert response.headers["Location"] == PREFIX + "/classic/"
    followed = requests.get(APP + "classic", timeout=10)
    assert followed.url == APP + "classic/"
    assert f"<p id='root-path'>{PREFIX}</p>" in followed.text


def test_interface_at_root_without_prefix(page: Page):
    requested, _ = open_interface(page, HARNESS_URL + "/")
    outside = [url for url in requested if urlparse(url).netloc == urlparse(HARNESS_URL).netloc and urlparse(url).path.startswith("/spark")]
    assert not outside
    result = page.evaluate("""async () => {
        const answer = await fetch('/api/v1/e2e/file-url').then(r => r.json())
        const image = new Image()
        image.src = answer.url
        return [answer.root_path, image.src]
    }""")
    assert result == ["", HARNESS_URL + "/api/v1/e2e/file/probe.png"]


def test_invalid_forwarded_prefix_is_ignored():
    for value in ("/a b", "https://evil.example/x", "//evil", "/x<script>"):
        answer = requests.get(
            HARNESS_URL + "/api/v1/e2e/file-url", headers={"X-Forwarded-Prefix": value}, timeout=10
        ).json()
        assert answer["root_path"] == "", value
