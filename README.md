# ⬢ NOMAD for Mac

**An offline knowledge base + local AI for when the internet is gone.**

When the power's out, the cell towers are down, or you're just somewhere remote,
NOMAD turns your Mac into a self-contained survival resource:

- 📚 **Offline library** — Wikipedia, medical encyclopedias, survival guides,
  water purification, repair manuals, and more. You pick what to download, so
  you control how much disk space it uses (from ~6 GB to 145+ GB).
- 🤖 **A local AI librarian** — a real language model running entirely on your
  Mac that can *search your offline library*, answer questions with cited
  sources, and help with general reasoning and problem-solving. No cloud, no
  account, no internet.

Everything runs locally and privately. After setup, NOMAD never needs the
internet again. (Inspired by [Project NOMAD](https://github.com/Crosstalk-Solutions/project-nomad),
which is Linux-only — this is a native Mac take on the same idea.)

## What you need

- A Mac with **Apple Silicon** (M1 or newer) and **16 GB+ memory** recommended.
  8 GB works with a smaller AI model; Intel Macs work but the AI is slow.
- Disk space for the library you choose (the picker shows sizes before downloading).
- Internet **for setup only**.

## Install (3 steps)

Open **Terminal** (press `⌘-Space`, type "Terminal") and paste:

```bash
git clone https://github.com/YOURNAME/nomad-mac.git
cd nomad-mac
./setup.sh
```

Setup installs everything (Homebrew, Ollama, the Kiwix library server, and an
AI model sized to your Mac's memory) and takes a few minutes plus the model
download. Then:

```bash
./nomad library    # choose your knowledge packs (presets or à la carte)
./nomad start      # opens the dashboard in your browser
```

That's it. The dashboard lives at `http://localhost:8900`.

## Using it

| Command | What it does |
|---|---|
| `./nomad start` | Start everything and open the dashboard |
| `./nomad stop` | Stop everything |
| `./nomad library` | Add or remove knowledge packs |
| `./nomad status` | Quick health check |
| `./nomad doctor` | Full offline-readiness check (run this before you need it!) |
| `./nomad logs` | Show recent logs if something's wrong |

**💡 Do a drill:** after setup, turn Wi-Fi off and run `./nomad doctor`. If it
passes, your Mac can answer questions with zero connectivity — that's the whole
point. A MacBook on battery + NOMAD = a working reference library during an outage.

## Keeping the library on an external drive

The library can live on an external SSD instead of your Mac — handy for big
libraries, and you can hand the drive to a friend. Run `./nomad library` and
pick your drive when asked where the library should live. To share: your friend
installs this repo (steps above), plugs in a copy of your drive, and picks it
in `./nomad library` — no re-downloading needed.

## What's in the library packs?

Highlights (sizes approximate; the picker shows live sizes):

- **Post Disaster Resource Library** (0.6 GB) — shelter, fire, sanitation, signaling
- **Water Treatment + Food Preparation** (0.2 GB) — purification and preservation
- **WikiMed + MDWiki + Emergency Medicine** (4 GB) — every medical article on Wikipedia, physician-curated references, field medicine
- **Wikipedia** — Simple (3 GB), Top Articles (6.5 GB), Full text (49 GB), or Full with images (119 GB)
- **iFixit + Home Improvement Q&A** (5 GB) — fix electronics, appliances, plumbing, wiring
- **Wikivoyage, Wiktionary, Project Gutenberg, Survivor Library** and more

Content comes from the [Kiwix](https://kiwix.org) project's free library.

## How it works

Three local services, all bound to your machine only:

| | |
|---|---|
| `kiwix-serve` (port 8090) | Serves the knowledge packs (ZIM files) with full-text search |
| Ollama (port 11434) | Runs the AI model on Apple Silicon's GPU |
| NOMAD app (port 8900) | The dashboard + chat. When you ask a question, the AI uses tools to search the library and read articles, then answers with source links. |

## FAQ

**Is the AI as good as ChatGPT?** No — it's a smaller model that fits on your
Mac. But because it searches a real reference library before answering, its
answers on survival/medical/repair topics are grounded in trusted sources it
cites, and it's genuinely useful for reasoning and everyday questions.

**Does anything leave my Mac?** No. Everything binds to `localhost`. Nothing
is sent anywhere, ever.

**Medical disclaimer:** NOMAD is an emergency reference, not a doctor. Get
professional care whenever it's available.
