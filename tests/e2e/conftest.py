"""Shared settings of the base path suite: addresses, readiness, local port.

The proxy and the harness are reached by their service names, which Chromium
treats as insecure origins, so the service worker API does not exist there.
Every address on localhost counts as a secure context, the way HTTPS does, so
the suite forwards LOCAL_URL (localhost:8080) to the proxy and loads the page
from there where it needs the service worker.
"""
import os
import socket
import socketserver
import threading
import time
from urllib.parse import urlparse

import pytest
import requests

PROXY_URL = os.environ.get("PROXY_URL", "http://proxy")
PREFIX = os.environ.get("PREFIX", "/spark-test/maestro")
HARNESS_URL = os.environ.get("HARNESS_URL", "http://harness:42100")
LOCAL_PORT = 8080
LOCAL_URL = f"http://localhost:{LOCAL_PORT}"


def wait_for(url, timeout=120):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            if requests.get(url, timeout=3).status_code == 200:
                return
        except requests.RequestException as error:
            last = error
        time.sleep(1)
    raise TimeoutError(f"{url} did not answer 200 within {timeout}s: {last}")


class Forward(socketserver.BaseRequestHandler):
    """Relay one TCP connection from the local port to the proxy."""

    def handle(self):
        target = urlparse(PROXY_URL)
        with socket.create_connection((target.hostname, target.port or 80)) as upstream:
            def pump(source, sink):
                try:
                    while data := source.recv(65536):
                        sink.sendall(data)
                except OSError:
                    pass
                finally:
                    try:
                        sink.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass

            back = threading.Thread(target=pump, args=(upstream, self.request), daemon=True)
            back.start()
            pump(self.request, upstream)
            back.join()


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


@pytest.fixture(scope="session", autouse=True)
def services_ready():
    wait_for(HARNESS_URL + "/")
    wait_for(PROXY_URL + PREFIX + "/")
    server = Server(("127.0.0.1", LOCAL_PORT), Forward)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    wait_for(LOCAL_URL + PREFIX + "/")
    yield
    server.shutdown()
    server.server_close()
