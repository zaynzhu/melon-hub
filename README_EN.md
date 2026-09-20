<div align="center">

# 🍈 melon-hub

[中文](README.md) | [English](README_EN.md)

[![GitHub Stars](https://img.shields.io/github/stars/zaynzhu/melon-hub?style=flat&logo=github)](https://github.com/zaynzhu/melon-hub/stargazers)
[![Last Commit](https://img.shields.io/github/last-commit/zaynzhu/melon-hub?style=flat&logo=git)](https://github.com/zaynzhu/melon-hub/commits/main)
[![Issues](https://img.shields.io/github/issues/zaynzhu/melon-hub?style=flat&logo=github)](https://github.com/zaynzhu/melon-hub/issues)

**Browse the latest posts from multiple content sources in one dashboard, with clean ad-free reading one click away.**

</div>

> [!TIP]
> melon-hub is a self-hosted aggregation reading panel: collectors fetch the latest articles from content sites into your own MySQL + RustFS (or local SQLite), a FastAPI backend serves clean reading APIs, and the web frontend offers card-flow / timeline views with a fullscreen reading drawer. All data lands in your own infrastructure — the repository itself contains no scraped content.

---

## ✨ Features

- **Multi-source aggregation** -- Switch between content sites via tabs, with card-flow / timeline / three-column views and per-source color coding
- **Clean reading** -- Ad-free article extraction, fullscreen reading drawer, instant open on cache hit
- **Dual storage drivers** -- Plug in your own MySQL + RustFS via config; falls back to SQLite + local directory automatically with identical interfaces
- **Reliable collection** -- Host-level 2s rate limiting, idempotent incremental runs, auto-stop on login walls or CAPTCHAs
- **Graceful degradation** -- Broken images replaced with placeholders; list thumbnails collected independently
- **Containerized** -- Single Docker container for API, frontend and scheduled collection (experimental)

---

## 🚀 Quick Start

```bash
git clone https://github.com/zaynzhu/melon-hub.git
cd melon-hub
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m collector.hl365
.venv/bin/python -m uvicorn server.app:app --port 8787
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787) and start browsing. Local storage works out of the box — no configuration required.

> [!NOTE]
> hl365 is collected via RSS directly, no browser needed. The other two sites sit behind Cloudflare, so their collectors require the kimi-webbridge browser channel on the host machine — see [Usage](#-usage).

---

## 📦 Installation

### Option 1: Run from source

```bash
git clone https://github.com/zaynzhu/melon-hub.git
cd melon-hub
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # optional: configure MySQL / RustFS; local storage is used otherwise
```

Main dependencies: `fastapi`, `uvicorn`, `requests`, `beautifulsoup4`, `PyYAML`, `boto3`, `PyMySQL`.

### Option 2: Docker (experimental)

```bash
docker build -t melon-hub .
docker run -d --name melon-hub -p 8787:8787 -v melon-data:/data melon-hub
```

The entrypoint collects hl365 once on boot and then hourly; API and frontend are served on port 8787.

---

## 💡 Usage

### Incremental collection

```bash
.venv/bin/python -m collector.hl365             # hl365: direct RSS, idempotent
.venv/bin/python -m collector.wacg51 --limit 8  # 51cg: browser-based, 8 articles per run
.venv/bin/python -m collector.mrds --limit 8    # mrds: same as above
```

### History backfill and thumbnails

```bash
.venv/bin/python -m collector.hl365 --backfill           # paginate list pages + text-only articles
.venv/bin/python -m collector.wacg51 --backfill --pages 4
.venv/bin/python -m collector.wacg51 --thumbs            # backfill list thumbnails (both sites)
.venv/bin/python -m collector.discover                   # mirror auto-discovery via homeway pages (--apply to write config)
```

### Launch the dashboard

```bash
.venv/bin/python -m uvicorn server.app:app --port 8787
```

Switch sites or the timeline view from the top bar, click any card for the fullscreen reading drawer, and use "view original" to jump to the source page.

---

## 🗺️ Roadmap

| 状态 | 事项 |
|------|------|
| ✅ | Multi-site browsing + fullscreen reading drawer + timeline view |
| ✅ | MySQL + RustFS storage with local fallback |
| ✅ | Paginated history backfill and list thumbnail collection |
| ✅ | Three-column overview and homeway mirror auto-discovery |
| 📋 | Cross-site dedup view |
| 📋 | Docker image build verification |

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [docs/handoffs/melon-hub.md](docs/handoffs/melon-hub.md) | Project handoff: architecture, decisions, current state |
| [docs/recon-upstream-2026-09-19.md](docs/recon-upstream-2026-09-19.md) | Upstream recon archive: data sources and domain findings |
| [config/sites.yaml](config/sites.yaml) | Collection config: origins, mirror pools, parsers |
| [.env.example](.env.example) | Environment template: database and object storage |

---

## 🤝 Contributing

This is a personal-use project; feature PRs are not accepted for now, but issues are welcome. Setting up a dev environment is the same as [Quick Start](#-quick-start); verify changes by running collectors twice for idempotency and smoke-testing the APIs with curl.

---

## ❓ FAQ

<details>
<summary>Why do some images show placeholders?</summary>

Some sites distribute images through an encrypted delivery pipeline that currently fails for every client (even on the source site itself). The frontend detects broken images and swaps in placeholders automatically — text reading is unaffected. Once the source recovers, a repair script can backfill the real images.
</details>

<details>
<summary>Where is the data stored?</summary>

With <code>.env</code> configured, data goes to your own MySQL and RustFS / S3; otherwise it falls back to local SQLite (<code>data/melon.db</code>) plus an object directory (<code>data/objects/</code>). The repository itself never contains scraped content.
</details>

<details>
<summary>Does collection stress the target sites?</summary>

Collectors enforce host-level 2-second rate limiting and idempotent incremental runs, stop immediately on login walls or CAPTCHAs, and never attempt to bypass site security mechanisms.
</details>

---

## ⚠️ Disclaimer

This project is a personal-use reading aggregation tool. It hosts, republishes and distributes no third-party content, and the repository contains no scraped data. All content comes from publicly accessible third-party sites and remains the property of its original owners; contact the owner for takedown requests. Comply with the laws and regulations of your jurisdiction when using it. No open-source license has been configured yet (all rights reserved by default).
