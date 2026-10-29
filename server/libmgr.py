"""Library manager: download, track, and remove knowledge packs from the web UI.

Downloads are resumable (curl -C -) and run at most two at a time. When a pack
finishes, the Kiwix server is restarted so the new content appears immediately.
Needs internet only while downloading new packs.
"""
import json
import os
import re
import shutil
import subprocess
import threading
import urllib.parse
import xml.etree.ElementTree as ET

import httpx

FIELDBOOK_DIR = os.environ.get("FIELDBOOK_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBRARY_DIR = os.environ.get("LIBRARY_DIR") or os.path.join(FIELDBOOK_DIR, "library")
ZIM_DIR = os.path.join(LIBRARY_DIR, "zim")
CATALOG_API = "https://library.kiwix.org/catalog/v2/entries"
ATOM = "{http://www.w3.org/2005/Atom}"

_sem = threading.Semaphore(2)
_lock = threading.Lock()
_jobs = {}  # pack id -> {"state": queued|downloading|done|error, "part", "total", "msg"}


def catalog():
    with open(os.path.join(FIELDBOOK_DIR, "catalog.json")) as f:
        return json.load(f)


def installed():
    if not os.path.isdir(ZIM_DIR):
        return []
    out = []
    for f in sorted(os.listdir(ZIM_DIR)):
        if f.endswith(".zim"):
            out.append({"file": f, "size": os.path.getsize(os.path.join(ZIM_DIR, f))})
    return out


def _is_installed(pack, files):
    prefix = pack["name"] + "_" + (pack["flavour"] + "_" if pack.get("flavour") else "")
    return any(f["file"].startswith(prefix) and re.match(r"\d", f["file"][len(prefix):]) for f in files)


def resolve(pack):
    """Live download URL + exact size from the Kiwix catalog, or None."""
    try:
        r = httpx.get(CATALOG_API, params={"name": pack["name"]}, timeout=30, follow_redirects=True)
        root = ET.fromstring(r.text)
    except Exception:
        return None
    for entry in root.iter(f"{ATOM}entry"):
        flavour = None
        for el in entry.iter():
            if el.tag.endswith("}flavour") or el.tag == "flavour":
                flavour = (el.text or "").strip() or None
        if pack.get("flavour") and flavour != pack["flavour"]:
            continue
        for link in entry.iter(f"{ATOM}link"):
            href = link.get("href") or ""
            if href.endswith(".meta4"):
                return href[: -len(".meta4")], int(link.get("length", "0"))
    return None


def _worker(pack):
    job = _jobs[pack["id"]]
    with _sem:
        job["state"] = "downloading"
        hit = resolve(pack)
        if not hit:
            job.update(state="error", msg="Couldn't reach the Kiwix catalog — are you online?")
            return
        url, size = hit
        dest = os.path.join(ZIM_DIR, os.path.basename(urllib.parse.urlparse(url).path))
        part = dest + ".part"
        if os.path.exists(dest):
            job["state"] = "done"
            return
        job.update(total=size, part=part)
        rc = subprocess.call(
            ["curl", "-sL", "-C", "-", "--fail", "--retry", "5", "--retry-delay", "5", "-o", part, url]
        )
        if rc != 0:
            job.update(state="error", msg="Download interrupted — press Download again to resume.")
            return
        # Byte-count check before installing: catches corrupt/overlapping downloads.
        if not os.path.exists(part) or os.path.getsize(part) != size:
            if os.path.exists(part):
                os.remove(part)
            if not os.path.exists(dest):
                job.update(state="error", msg="Download didn't verify — press Download to retry.")
                return
        else:
            os.replace(part, dest)
        job["state"] = "done"
        subprocess.call([os.path.join(FIELDBOOK_DIR, "fieldbook"), "restart-kiwix"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def start_download(pack_id):
    packs = {p["id"]: p for p in catalog()["packs"]}
    pack = packs.get(pack_id)
    if not pack:
        return {"error": "unknown pack"}
    with _lock:
        job = _jobs.get(pack_id)
        if job and job["state"] in ("queued", "downloading"):
            return {"ok": True}  # already underway
        os.makedirs(ZIM_DIR, exist_ok=True)
        _jobs[pack_id] = {"state": "queued", "part": None, "total": 0, "msg": ""}
    threading.Thread(target=_worker, args=(pack,), daemon=True).start()
    return {"ok": True}


def delete(filename):
    files = [f["file"] for f in installed()]
    if filename not in files:
        return {"error": "no such pack file"}
    os.remove(os.path.join(ZIM_DIR, filename))
    subprocess.call([os.path.join(FIELDBOOK_DIR, "fieldbook"), "restart-kiwix"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True}


def status():
    cat = catalog()
    files = installed()
    jobs = {}
    for pid, job in _jobs.items():
        done = 0
        if job.get("part") and os.path.exists(job["part"]):
            done = os.path.getsize(job["part"])
        jobs[pid] = {"state": job["state"], "done": done, "total": job["total"], "msg": job["msg"]}
    packs = []
    for p in cat["packs"]:
        packs.append({**p, "installed": _is_installed(p, files)})
    try:
        free = shutil.disk_usage(LIBRARY_DIR if os.path.isdir(LIBRARY_DIR) else FIELDBOOK_DIR).free
    except OSError:
        free = 0
    return {"packs": packs, "presets": cat["presets"], "installed": files,
            "jobs": jobs, "free": free, "library_dir": LIBRARY_DIR}
