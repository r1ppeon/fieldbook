#!/usr/bin/env python3
"""Fieldbook library manager: pick, download, and remove offline knowledge packs.

Uses only the Python standard library so it works before setup finishes.
Pack metadata (exact download URL + current size) is resolved live from the
Kiwix catalog API, so this repo never goes stale when Kiwix updates content.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

FIELDBOOK_DIR = os.environ.get("FIELDBOOK_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG_API = "https://library.kiwix.org/catalog/v2/entries"
ATOM = "{http://www.w3.org/2005/Atom}"

BOLD, DIM, GREEN, YELLOW, RED, RESET = "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[0m"


def gb(nbytes):
    return nbytes / 2**30


def human(nbytes):
    g = gb(nbytes)
    return f"{g:.1f} GB" if g >= 1 else f"{nbytes / 2**20:.0f} MB"


def load_catalog():
    with open(os.path.join(FIELDBOOK_DIR, "catalog.json")) as f:
        return json.load(f)


def library_dir():
    """Where ZIM files live. First run (or missing drive) prompts for a location."""
    lib = os.environ.get("LIBRARY_DIR", os.path.join(FIELDBOOK_DIR, "library"))
    local_cfg = os.path.join(FIELDBOOK_DIR, "config.local.sh")
    if not os.path.isdir(os.path.dirname(lib)) and lib.startswith("/Volumes/"):
        print(f"{RED}Your library drive ({os.path.dirname(lib)}) isn't plugged in.{RESET}")
        print("Plug it in and run this again, or choose a new location below.\n")
    elif os.path.isdir(os.path.join(lib, "zim")) or os.path.exists(local_cfg):
        os.makedirs(os.path.join(lib, "zim"), exist_ok=True)
        return lib

    print(f"{BOLD}Where should your knowledge library live?{RESET}")
    print("  1. On this Mac  (" + os.path.join(FIELDBOOK_DIR, "library") + ")")
    vols = [v for v in sorted(os.listdir("/Volumes")) if v != "Macintosh HD"]
    for i, v in enumerate(vols, start=2):
        free = human(shutil.disk_usage(f"/Volumes/{v}").free)
        print(f"  {i}. External drive: /Volumes/{v}  ({free} free)")
    choice = input("Choose [1]: ").strip() or "1"
    if choice == "1" or not choice.isdigit() or int(choice) - 2 >= len(vols):
        lib = os.path.join(FIELDBOOK_DIR, "library")
    else:
        lib = f"/Volumes/{vols[int(choice) - 2]}/fieldbook-library"
        with open(local_cfg, "a") as f:
            f.write(f'LIBRARY_DIR="{lib}"\n')
        print(f"Saved: library will live at {lib}")
    os.makedirs(os.path.join(lib, "zim"), exist_ok=True)
    return lib


def resolve(pack):
    """Look up a pack in the live Kiwix catalog -> (url, size_bytes) or None."""
    q = urllib.parse.urlencode({"name": pack["name"]})
    try:
        with urllib.request.urlopen(f"{CATALOG_API}?{q}", timeout=30) as r:
            root = ET.fromstring(r.read())
    except Exception as e:
        print(f"{RED}  couldn't reach the Kiwix catalog ({e}){RESET}")
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


def installed_zims(lib):
    zdir = os.path.join(lib, "zim")
    return sorted(f for f in os.listdir(zdir) if f.endswith(".zim")) if os.path.isdir(zdir) else []


def is_installed(pack, zims):
    prefix = pack["name"] + "_" + (pack["flavour"] + "_" if pack.get("flavour") else "")
    return any(z.startswith(prefix) and re.match(r"\d", z[len(prefix):]) for z in zims)


def download(pack, url, size, lib):
    dest = os.path.join(lib, "zim", os.path.basename(urllib.parse.urlparse(url).path))
    part = dest + ".part"
    print(f"\n{BOLD}Downloading {pack['title']}{RESET} ({human(size)})")
    print(f"{DIM}{url}{RESET}")
    # curl: resumable (-C -), follows mirror redirects, retries on flaky network
    rc = subprocess.call(["curl", "-L", "-C", "-", "--fail", "--retry", "5",
                          "--retry-delay", "5", "-o", part, url])
    if rc != 0:
        print(f"{RED}Download interrupted — run './fieldbook library' again to resume where it left off.{RESET}")
        return False
    os.rename(part, dest)
    print(f"{GREEN}Done: {os.path.basename(dest)}{RESET}")
    return True


def pick_packs(cat, zims):
    packs = cat["packs"]
    print(f"\n{BOLD}=== Fieldbook Knowledge Library ==={RESET}\n")
    print(f"{BOLD}Quick presets:{RESET}")
    preset_keys = list(cat["presets"])
    for i, key in enumerate(preset_keys, 1):
        p = cat["presets"][key]
        print(f"  {i}. {BOLD}{p['label']}{RESET} — {p['desc']}")
    print(f"\n{BOLD}Or pick individual packs:{RESET}")
    n = len(preset_keys)
    last_cat = None
    for i, pack in enumerate(packs, n + 1):
        if pack["category"] != last_cat:
            last_cat = pack["category"]
            print(f"\n  {DIM}{last_cat}{RESET}")
        mark = f"{GREEN}✓ installed{RESET}" if is_installed(pack, zims) else f"~{pack['approx_gb']:g} GB"
        print(f"  {i:2}. {pack['title']:<42} {mark}")
        print(f"      {DIM}{pack['desc']}{RESET}")
    print(f"\nEnter numbers separated by spaces (e.g. '1' for a preset, or '5 9 12'),")
    raw = input("'d' to delete packs, or 'q' to quit: ").strip().lower()
    if raw in ("q", ""):
        return None
    if raw == "d":
        return "delete"
    chosen, ids = [], set()
    for tok in raw.split():
        if not tok.isdigit():
            continue
        k = int(tok)
        if 1 <= k <= n:
            ids.update(cat["presets"][preset_keys[k - 1]]["packs"])
        elif n < k <= n + len(packs):
            ids.add(packs[k - n - 1]["id"])
    for pack in packs:
        if pack["id"] in ids and not is_installed(pack, zims):
            chosen.append(pack)
    return chosen


def delete_menu(lib, zims):
    if not zims:
        print("Nothing installed yet.")
        return
    print(f"\n{BOLD}Installed packs:{RESET}")
    for i, z in enumerate(zims, 1):
        size = os.path.getsize(os.path.join(lib, "zim", z))
        print(f"  {i:2}. {z}  ({human(size)})")
    raw = input("Numbers to DELETE (or enter to cancel): ").strip()
    for tok in raw.split():
        if tok.isdigit() and 1 <= int(tok) <= len(zims):
            victim = zims[int(tok) - 1]
            if input(f"Really delete {victim}? [y/N]: ").strip().lower() == "y":
                os.remove(os.path.join(lib, "zim", victim))
                print(f"Deleted {victim}")


def main():
    cat = load_catalog()
    lib = library_dir()
    zims = installed_zims(lib)
    chosen = pick_packs(cat, zims)
    if chosen is None:
        return
    if chosen == "delete":
        delete_menu(lib, zims)
        return
    if not chosen:
        print("Everything you picked is already installed.")
        return

    # Warn once about giant packs, resolve live sizes, check disk space.
    for pack in [p for p in chosen if p.get("warn_huge")]:
        if input(f"{YELLOW}{pack['title']} is ~{pack['approx_gb']:g} GB. Download it? [y/N]:{RESET} ").strip().lower() != "y":
            chosen.remove(pack)
    dupes = {}
    for p in chosen:
        if p.get("group"):
            dupes.setdefault(p["group"], []).append(p["title"])
    for titles in dupes.values():
        if len(titles) > 1:
            print(f"{YELLOW}Note: {' and '.join(titles)} overlap (same content, different sizes).{RESET}")

    print(f"\n{BOLD}Checking current sizes with the Kiwix catalog...{RESET}")
    plan, total = [], 0
    for pack in chosen:
        hit = resolve(pack)
        if not hit:
            print(f"{RED}  {pack['title']}: not found in catalog right now — skipping.{RESET}")
            continue
        url, size = hit
        plan.append((pack, url, size))
        total += size
        print(f"  {pack['title']:<42} {human(size)}")
    if not plan:
        return
    free = shutil.disk_usage(lib).free
    print(f"\nTotal download: {BOLD}{human(total)}{RESET}   Free space there: {human(free)}")
    if total > free:
        print(f"{RED}Not enough free space at {lib}. Pick less, or move the library to a bigger drive.{RESET}")
        return
    if input("Start downloads? [Y/n]: ").strip().lower() in ("n", "no"):
        return
    ok = sum(download(pack, url, size, lib) for pack, url, size in plan)
    print(f"\n{GREEN}{ok}/{len(plan)} packs installed.{RESET} Run {BOLD}./fieldbook start{RESET} to use them.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n(cancelled — partial downloads resume automatically next time)")
