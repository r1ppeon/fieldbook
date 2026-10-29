"""NOMAD dashboard + chat server. Localhost only; works fully offline."""
import json
import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import librarian, libmgr

KIWIX_PORT = os.environ.get("KIWIX_PORT", "8090")
WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

app = FastAPI(title="NOMAD for Mac")


@app.get("/api/status")
def status():
    def ping(url):
        try:
            httpx.get(url, timeout=2)
            return True
        except Exception:
            return False
    books = librarian.list_books()
    return {
        "kiwix": ping(f"http://127.0.0.1:{KIWIX_PORT}/"),
        "ollama": ping("http://127.0.0.1:11434/"),
        "model": librarian.MODEL,
        "kiwix_port": KIWIX_PORT,
        "books": books,
    }


@app.get("/api/library")
def library_status():
    return libmgr.status()


@app.post("/api/library/download")
async def library_download(request: Request):
    body = await request.json()
    ids = body.get("ids") or [body.get("id")]
    results = [libmgr.start_download(pid) for pid in ids if pid]
    return {"ok": all(r.get("ok") for r in results), "results": results}


@app.post("/api/library/delete")
async def library_delete(request: Request):
    body = await request.json()
    return libmgr.delete(body.get("file", ""))


@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    messages = body.get("messages", [])

    def event_stream():
        for event in librarian.chat(messages):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
