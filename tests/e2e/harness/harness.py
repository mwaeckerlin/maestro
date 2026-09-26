"""Serve the built Maestro interface of the image without a GPU.

The Maestro server imports its engine at start, and the engine asks CUDA for
the GPU; without one it stops. This harness serves what the image delivers to
the browser — ui/dist with the base path script, behind maestro_serve's
ForwardedPrefix — and answers the requests the base path tests make. It stands
in for the Maestro backend only; the full server is tested on a GPU host by
`npm run test:gpu`.
"""
import asyncio
import base64
import sys

sys.path.insert(0, "/opt/maestro/src/app")

import uvicorn  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from maestro_serve import ForwardedPrefix, bind_address  # noqa: E402

# A 1x1 PNG, so an <img> can prove it loaded.
PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

api = FastAPI()
requests_seen = []


@api.middleware("http")
async def record(request: Request, call_next):
    requests_seen.append({"path": request.url.path, "root_path": request.scope.get("root_path", "")})
    return await call_next(request)


@api.get("/api/v1/e2e/file-url")
def file_url(request: Request):
    # The same shape as Maestro's answers: a root-absolute file address.
    return {"url": "/api/v1/e2e/file/probe.png", "root_path": request.scope.get("root_path", "")}


@api.get("/api/v1/e2e/file/{name}")
def file(name: str):
    return Response(PIXEL, media_type="image/png")


@api.get("/api/v1/e2e/seen")
def seen():
    return JSONResponse(requests_seen[-200:])


@api.get("/classic")
def classic_redirect():
    # Maestro answers the bare /classic with exactly this redirect.
    return RedirectResponse(url="/classic/")


@api.get("/classic/")
def classic(request: Request):
    return HTMLResponse(f"<p id='root-path'>{request.scope.get('root_path', '')}</p>")


@api.get("/maestro-icon.png")
def icon():
    return Response(PIXEL, media_type="image/png")


api.mount("/", StaticFiles(directory="/opt/maestro/src/ui/dist", html=True))

if __name__ == "__main__":
    # The launcher's own reading of MAESTRO_HOST and MAESTRO_PORT.
    host, port = bind_address()
    asyncio.run(uvicorn.Server(uvicorn.Config(ForwardedPrefix(api), host=host, port=port)).serve())
