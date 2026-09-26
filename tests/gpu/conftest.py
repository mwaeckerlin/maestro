"""Shared settings of the GPU suite: the proxy address and readiness.

Maestro imports its engine and builds its model registry before it listens;
the first start of a container waits for that, so the readiness limit is long.
"""
import os
import time

import pytest
import requests

PROXY_URL = os.environ.get("PROXY_URL", "http://proxy")
PREFIX = os.environ.get("PREFIX", "/spark-test/maestro")


@pytest.fixture(scope="session", autouse=True)
def maestro_ready():
    url = PROXY_URL + PREFIX + "/api/v1/system-detect"
    deadline = time.time() + 900
    last = None
    while time.time() < deadline:
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                return
            last = response.status_code
        except requests.RequestException as error:
            last = error
        time.sleep(5)
    raise TimeoutError(f"{url} did not answer 200 within 900s: {last}")
