"""The NOMAD librarian: a local LLM that can search and read the offline library.

Everything here talks only to localhost — Ollama (the model) and kiwix-serve
(the knowledge library). Nothing requires the internet.

Two kinds of knowledge packs are handled:
- Indexed packs (Wikipedia, WikiMed, iFixit...): kiwix-serve full-text search.
- Document packs (the zimgit survival collections): no full-text index; they
  ship a database.js catalog of PDFs, which we match by title/description and
  read with pypdf.
"""
import ast
import io
import json
import os
import re
import xml.etree.ElementTree as ET

import httpx
import ollama
from bs4 import BeautifulSoup

KIWIX = f"http://127.0.0.1:{os.environ.get('KIWIX_PORT', '8090')}"
MODEL = os.environ.get("NOMAD_MODEL", "qwen3:8b")
ATOM = "{http://www.w3.org/2005/Atom}"

SYSTEM_PROMPT = """You are the NOMAD librarian, an offline assistant running on the user's own \
Mac with no internet. You have access to their offline knowledge library (Wikipedia, medical \
references, survival guides, repair manuals) through two tools.

Rules:
- For factual, medical, survival, or how-to questions, ALWAYS use search_library first, and \
read_article on the most promising result before answering. Ground your answer in what you read.
- Answer plainly and practically. In emergencies, give clear numbered steps, most important first.
- If the library has nothing relevant, say so, then answer from your general knowledge — and \
begin that answer with "From general knowledge (not found in your library):". Never present an \
unverified number, dose, or measurement as certain.
- You may be helping someone in a real disaster: be calm, specific, and safety-conscious. For \
serious medical situations, include when professional care is essential.
- General conversation, reasoning, and problem-solving don't need the tools."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_library",
            "description": "Search the whole offline library (encyclopedia articles and survival/medical documents). Returns titles, snippets, and paths.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search terms, e.g. 'water purification boiling'"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_article",
            "description": "Read the full text of one article or document found by search_library.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "The 'path' exactly as returned by search_library"}},
                "required": ["path"],
            },
        },
    },
]

_toc_cache = {}


def list_books():
    """Books served by kiwix-serve: [{'title', 'content_id', 'ftindex'}]."""
    try:
        r = httpx.get(f"{KIWIX}/catalog/v2/entries", params={"count": 200}, timeout=10)
        root = ET.fromstring(r.text)
    except Exception:
        return []
    books = []
    for entry in root.iter(f"{ATOM}entry"):
        title = entry.findtext(f"{ATOM}title") or "?"
        tags = entry.findtext(f"{ATOM}tags") or ""
        content_id = None
        for link in entry.iter(f"{ATOM}link"):
            href = link.get("href") or ""
            if link.get("type") == "text/html" and href.startswith("/content/"):
                content_id = href.split("/content/", 1)[1].strip("/")
        if content_id:
            books.append({"title": title, "content_id": content_id,
                          "ftindex": "_ftindex:no" not in tags})
    return books


def _fulltext_search(query):
    """kiwix-serve full-text search across every indexed book."""
    results = []
    try:
        r = httpx.get(f"{KIWIX}/search", params={"pattern": query, "pageLength": 10}, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select(".results a[href]"):
            item = a.find_parent("li") or a.parent
            snippet = " ".join(item.get_text(" ", strip=True).split())[:300] if item else ""
            results.append({"title": a.get_text(strip=True), "path": a["href"], "snippet": snippet})
    except Exception:
        pass
    return results


def _pack_toc(book):
    """The document list of a zimgit-style pack, from its database.js."""
    if book["content_id"] in _toc_cache:
        return _toc_cache[book["content_id"]]
    docs = []
    try:
        r = httpx.get(f"{KIWIX}/content/{book['content_id']}/database.js", timeout=10)
        if r.status_code == 200:
            for raw in re.findall(r"\{[^{}]*\}", r.text):
                try:
                    e = ast.literal_eval(raw)
                except (ValueError, SyntaxError):
                    continue
                if isinstance(e, dict) and e.get("ti") and e.get("fp"):
                    docs.append({
                        "title": e["ti"],
                        "desc": f"{e.get('dsc', '')} ({e.get('aut', '')})".strip(),
                        "path": f"/content/{book['content_id']}/files/{e['fp'][0]}",
                        "book": book["title"],
                    })
    except Exception:
        pass
    _toc_cache[book["content_id"]] = docs
    return docs


def _toc_search(query, books):
    """Match query words against document titles/descriptions in no-index packs."""
    words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2]
    if not words:
        return []
    scored = []
    for book in books:
        for doc in _pack_toc(book):
            hay = f"{doc['title']} {doc['desc']}".lower()
            score = sum(hay.count(w) for w in words)
            if score:
                scored.append((score, doc))
    scored.sort(key=lambda s: -s[0])
    return [{"title": d["title"], "path": d["path"], "snippet": f"[{d['book']}] {d['desc']}"}
            for _, d in scored[:8]]


def search_library(query):
    books = list_books()
    results = _fulltext_search(query) + _toc_search(query, [b for b in books if not b["ftindex"]])
    if not results:
        return {"results": [], "note": "No matches in the library. Try simpler or different words."}
    return {"results": results[:16]}


def _pdf_text(data):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages[:15]]
    return " ".join(" ".join(pages).split())


def read_article(path):
    """Fetch one article/document from kiwix-serve and return readable text."""
    if not path.startswith("/"):
        path = "/" + path
    try:
        r = httpx.get(f"{KIWIX}{path}", timeout=30, follow_redirects=True)
        r.raise_for_status()
    except Exception as e:
        return {"error": f"Could not read that article: {e}"}

    if "pdf" in r.headers.get("content-type", "") or path.lower().endswith(".pdf"):
        try:
            text = _pdf_text(r.content)
        except Exception as e:
            return {"error": f"Couldn't extract PDF text ({e}). Give the user the link instead.",
                    "title": os.path.basename(path), "path": path}
        if len(text) < 200:
            return {"title": os.path.basename(path), "path": path,
                    "note": "This document is a scanned image without machine-readable text. "
                            "Tell the user to open it via the source link.", "text": text}
        return {"title": os.path.basename(path), "path": path, "text": text[:8000]}

    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else path
    text = " ".join(soup.get_text(" ", strip=True).split())
    return {"title": title, "path": path, "text": text[:8000]}


def _run_tool(name, args, sources):
    if name == "search_library":
        return search_library(args.get("query", ""))
    if name == "read_article":
        out = read_article(args.get("path", ""))
        if out.get("path") and not out.get("error"):
            sources.append({"title": out.get("title", "source"), "href": f"{KIWIX}{out['path']}"})
        return out
    return {"error": f"unknown tool {name}"}


def chat(messages, max_rounds=6):
    """Generator of events: {'type': 'status'|'token'|'sources'|'error'|'done', ...}

    Runs the model with tool access; streams answer tokens as they arrive.
    """
    client = ollama.Client()
    convo = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
    sources = []

    for _ in range(max_rounds):
        kwargs = dict(model=MODEL, messages=convo, tools=TOOLS, stream=True)
        try:
            stream = client.chat(think=False, **kwargs)
            chunks = iter(stream)
            first = next(chunks, None)
        except (TypeError, ollama.ResponseError):
            # Model or client doesn't support think=False
            stream = client.chat(**kwargs)
            chunks = iter(stream)
            first = next(chunks, None)
        except Exception as e:
            yield {"type": "error", "text": f"Can't reach the AI engine (is Ollama running?): {e}"}
            return

        content, tool_calls = "", []
        chunk = first
        while chunk is not None:
            msg = chunk.get("message", {}) if isinstance(chunk, dict) else chunk.message
            piece = msg.get("content") if isinstance(msg, dict) else msg.content
            calls = msg.get("tool_calls") if isinstance(msg, dict) else msg.tool_calls
            if piece:
                content += piece
                yield {"type": "token", "text": piece}
            if calls:
                tool_calls.extend(calls)
            chunk = next(chunks, None)

        if not tool_calls:
            if sources:
                yield {"type": "sources", "items": sources}
            else:
                # Nothing from the library backs this answer — let the UI say so.
                yield {"type": "ungrounded"}
            yield {"type": "done"}
            return

        convo.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
        for call in tool_calls:
            fn = call.get("function", {}) if isinstance(call, dict) else call.function
            name = fn.get("name") if isinstance(fn, dict) else fn.name
            args = fn.get("arguments") if isinstance(fn, dict) else fn.arguments
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            label = args.get("query") or args.get("path") or ""
            yield {"type": "status", "text": f"{'Searching library for' if name == 'search_library' else 'Reading'}: {label}"}
            result = _run_tool(name, args or {}, sources)
            convo.append({"role": "tool", "content": json.dumps(result)[:12000]})

    yield {"type": "error", "text": "The librarian got stuck searching. Try rephrasing your question."}
