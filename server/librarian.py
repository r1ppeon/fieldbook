"""The NOMAD librarian: a local LLM that can search and read the offline library.

Everything here talks only to localhost — Ollama (the model) and kiwix-serve
(the knowledge library). Nothing requires the internet.
"""
import json
import os
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
- If the library has nothing relevant, say so, then answer from your general knowledge and note \
that it wasn't verified against the library.
- You may be helping someone in a real disaster: be calm, specific, and safety-conscious. For \
serious medical situations, include when professional care is essential.
- General conversation, reasoning, and problem-solving don't need the tools."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_library",
            "description": "Full-text search across every book in the offline library. Returns titles, snippets, and paths.",
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
            "description": "Read the full text of one article found by search_library.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "The article 'path' exactly as returned by search_library"}},
                "required": ["path"],
            },
        },
    },
]


def list_books():
    """Books currently served by kiwix-serve: [{'name', 'title'}]."""
    try:
        r = httpx.get(f"{KIWIX}/catalog/v2/entries", params={"count": 200}, timeout=10)
        root = ET.fromstring(r.text)
    except Exception:
        return []
    books = []
    for entry in root.iter(f"{ATOM}entry"):
        name = next((el.text for el in entry.iter() if el.tag.endswith("}name") or el.tag == "name"), None)
        title = entry.findtext(f"{ATOM}title")
        if name:
            books.append({"name": name, "title": title or name})
    return books


def search_library(query):
    """Search every book; merge the best results."""
    results = []
    for book in list_books():
        try:
            r = httpx.get(
                f"{KIWIX}/search",
                params={"books.name": book["name"], "pattern": query, "pageLength": 4},
                timeout=15,
            )
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.select(".results a[href]"):
                snippet_el = a.find_parent("li") or a.parent
                snippet = " ".join(snippet_el.get_text(" ", strip=True).split())[:300] if snippet_el else ""
                results.append({
                    "title": a.get_text(strip=True),
                    "path": a["href"],
                    "book": book["title"],
                    "snippet": snippet,
                })
        except Exception:
            continue
    if not results:
        return {"results": [], "note": "No matches in the library for that query. Try different words."}
    return {"results": results[:16]}


def read_article(path):
    """Fetch one article from kiwix-serve and return readable text."""
    if not path.startswith("/"):
        path = "/" + path
    try:
        r = httpx.get(f"{KIWIX}{path}", timeout=20, follow_redirects=True)
        r.raise_for_status()
    except Exception as e:
        return {"error": f"Could not read that article: {e}"}
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else path
    text = " ".join(soup.get_text(" ", strip=True).split())
    return {"title": title, "path": path, "text": text[:8000]}


def _run_tool(name, args, sources):
    if name == "search_library":
        out = search_library(args.get("query", ""))
        return out
    if name == "read_article":
        out = read_article(args.get("path", ""))
        if "title" in out:
            sources.append({"title": out["title"], "href": f"{KIWIX}{out['path']}"})
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
