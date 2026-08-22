# tabby-stack

Install this on an Arch Linux box that has an NVIDIA GPU. That box becomes a **private coding assistant and image generator**. You keep using Cursor, VS Code, Continue, Cline, or a script on any other machine — you just point your editor or IDE at this box instead of OpenAI.

There is no extra chat window on the GPU machine. Your editor or IDE is the UI.

![A short walkthrough in your editor or IDE: help, list models, switch, then a page plus generated images](docs/ide-chat.gif)

## What you get

- Chat and code help from a model that runs on **your** GPU
- Image generation on the **same** API URL
- A way to switch models from chat (`switch to qwen`, `switch to comfy`, …)
- An Arch installer that sets packages, Python, model weights, and a service that starts at boot

Aimed at a 12 GB NVIDIA card (RTX 4070-class). Prompts stay on your machines unless you open a public tunnel.

This is not ChatGPT, not Cursor’s cloud models, and not a desktop app. The git repo is the software. Model weights download during install (or copy from a folder you already have).

## Two machines

| Machine | What it does |
|---|---|
| **GPU host** (Arch Linux) | Runs the API, the language model, and image generation |
| **Your computer** | Runs your editor or IDE. You open your project here. |

After install, the API listens on the GPU host. In your editor or IDE set:

- **Base URL:** `http://<gpu-host>:5000/v1` (or your LAN / Tailscale / tunnel URL)
- **Model:** `gpt-4o`

`gpt-4o` is only a label. Many editors refuse tools unless they see a familiar OpenAI name. The GPU still runs whichever local model you last switched to — usually **qwen** for daily coding.

## Install

**Needs:** Arch Linux, an NVIDIA GPU, internet. Run as **your user**, not root. Install onto the Linux disk, not a USB.

```bash
sudo pacman -S --needed git
git clone https://github.com/styelz/tabby-stack-archlinux.git
cd tabby-stack-archlinux
bash install.sh
```

Default destination: `$HOME/tabby-stack`. The installer asks for the install folder, an optional weights cache, which models to download, and which addresses to listen on.

- **core** — enough to code and make images (qwen 9B, Flux, Qwen-Image, plus a small embedder on CPU)
- **all** — those, plus the larger models in the switch list below

If Hugging Face returns 401 or 403, run `huggingface-cli login` (or set `HF_TOKEN`) and re-run.

USB cache, non-interactive flags, and troubleshooting: [tabbyAPI/deploy/arch/README.md](tabbyAPI/deploy/arch/README.md).

## First use

The installer starts the API at boot (no login needed). Check that it is up:

```bash
curl -sS http://127.0.0.1:5000/health
```

If it is stopped:

```bash
systemctl --user enable --now tabbyapi
```

Logs: `journalctl --user -u tabbyapi -f`

In your editor or IDE, send a message that is **only** one of these phrases — the whole message, not “please switch to qwen”:

| Phrase | What it does | Ready (warm, 4070 Ti 12 GB) |
|---|---|---|
| `help` | Usage guide | — |
| `list models` | Show what is installed | — |
| `restart` | Bounce the API; last model reloads | ~65 seconds |
| `switch to qwen` | Daily coding (9B). Start here. | ~65 seconds |
| `switch to qwen35` | Longer or harder agent work | ~3 minutes |
| `switch to qwen36` | Longer or harder agent work | ~85 seconds |
| `switch to gemma` | General chat | ~65 seconds |
| `switch to gemma26` | Larger general model | ~2 minutes |
| `switch to glm` | Thinking (vision is off on 12 GB) | ~15 seconds |
| `switch to comfy` / `flux` | Hand the GPU to image generation | ~35 seconds, then the picture |
| `switch to llm` | Free image gen; reload the last coding model | ~65 seconds |

The card can run **chat or images, not both at once**. First Flux picture ~3 minutes; first Qwen-Image ~4 minutes. After that, the coding model takes about 65 seconds to come back.

Daily work stays on `qwen`. Notes for any editor or IDE: [AGENTS.md](AGENTS.md).

## Images

**Just a picture.** Send `generate an image of a neon diner at night`. The API moves the GPU to image generation, returns a PNG URL on the same host, then reloads the coding model.

- Photos and scenes (headers, backgrounds): describe the **scene**, not a website.
- Logos, posters, buttons, anything with **readable words**: start the prompt with `qwen-image:`, e.g. `qwen-image: a logo that says Harbor Cafe`.

You can also send `switch to comfy`, wait until it is ready, then describe the picture. When you are done, `switch to qwen` (or `switch to llm`).

**A page plus its pictures.** A line like “create a landing page and generate a header and logo” is a **coding** request. The agent should write the HTML/CSS into files, generate the PNGs, and point the page at those files — not paste a screenshot of a finished site into the header.

```
Create a cafe landing page under harbor/. Write the HTML and CSS.
Generate harbor/images/header.png of a neon diner street at night,
and qwen-image: harbor/images/logo.png that says Harbor Cafe.
Point the page at those files.
```

Name the PNG paths under the site folder, or they land in `images/` at the project root. Budget about 3 minutes per Flux picture, 4 minutes per Qwen-Image, then about 65 seconds to bring the coding model back.

## Saving PNGs into the project

The API returns a URL. The agent downloads that file into the project. Chat phrases and `POST /v1/images/generations` work in any editor that can call an OpenAI-compatible API.

For a page plus pictures, the API starts the image job from the user line and then drives the download. You do not add a plugin or an `mcp.json` for that.

## License

TabbyAPI code is [AGPL-3.0](LICENSE), the same as [upstream TabbyAPI](https://github.com/theroyallab/tabbyAPI). ComfyUI, custom nodes, and downloaded weights have their own licenses.
