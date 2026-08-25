# tabby-stack

A self-hosted coding assistant, web workspace, and image generator for an Arch Linux machine with an NVIDIA GPU.

Use it from Cursor, VS Code, Continue, Cline, another OpenAI-compatible client, or the built-in browser UI. Prompts, project files, and generated images stay on hardware you control.

![An editor using Tabby Stack to build and preview a site](docs/ide-preview.jpg)

## What you get

- An OpenAI-compatible API for local chat, tool use, vision, and embeddings
- Switchable language-model profiles tuned for a 12 GB NVIDIA card
- Flux Schnell and Qwen-Image through ComfyUI
- A browser UI with Chat and Code workspaces, status graphs, logs, a gallery, and user accounts
- A guided Arch installer plus systemd startup, updates, and an optional HTTPS reverse tunnel

The language model and ComfyUI share one GPU. Tabby Stack unloads one before starting the other; the CPU embedding model can remain available throughout.

```mermaid
flowchart LR
    Editor["Editor on your computer"] --> API["TabbyAPI /v1"]
    Browser["Browser /v1/ui"] --> API
    API --> CPU["CPU embeddings"]
    API --> GPU{"NVIDIA GPU"}
    GPU --> LLM["Coding / chat model"]
    GPU --> Images["ComfyUI image models"]
```

## Install

Requirements: Arch Linux, an NVIDIA GPU, internet access, and enough disk space for the selected model set. Run the installer as your normal user, not as root.

```bash
sudo pacman -S --needed git
git clone https://github.com/styelz/tabby-stack-archlinux.git "$HOME/tabby-stack"
cd "$HOME/tabby-stack"
bash install.sh
```

The installer asks where to install, whether to reuse a weights cache, which models to fetch, what addresses to listen on, and whether to configure a public URL or reverse SSH tunnel.

Choose:

- **core** for qwen 9B, Flux, Qwen-Image, and the CPU embedder
- **all** to add every larger switchable model profile

It is safe to run the installer again: existing weights are skipped. For USB caches, unattended installation, network settings, and recovery steps, use the [complete Arch install guide](tabbyAPI/deploy/arch/README.md).

## Start and sign in

The installer enables a user service that starts at boot, even before login.

```bash
curl -sS http://127.0.0.1:5000/health
systemctl --user status tabbyapi
journalctl --user -u tabbyapi -f
```

Open `http://127.0.0.1:5000/v1/ui` on the GPU host, or `/v1/ui` under the public URL you configured. Sign in with the Linux account that installed the stack.

The first account is the administrator. It can create separate Tabby-only accounts from **Users**; those accounts do not become Linux users. Conversations, Code projects, and images are kept per account, while the administrator can manage users and view all gallery images.

## Use the browser UI

**Chat** is for conversations, pasted images, model commands, and image generation. It keeps searchable history and lets you queue a follow-up while a reply is running.

**Code** gives every conversation its own project folder. Ask the model to create or edit files, upload existing files, edit them in the browser IDE, preview an HTML site, use a jailed terminal, or download the project as a zip.

![Code mode with chat, project files, and site controls](docs/ui-code.jpg)

Other pages:

| Page | What it is for |
|---|---|
| **Status** | Loaded profile, GPU mode, health, CPU/RAM/NVIDIA metrics, model switching, restart, and updates |
| **Gallery** | Preview and download generated images; administrators can see all users |
| **Logs** | Live and historical TabbyAPI and ComfyUI output |
| **Users** | Administrator-only account creation, password reset, and deletion |

![Status and resource history](docs/ui-status.jpg)

![Generated image gallery](docs/ui-gallery.jpg)

## Connect an editor

Configure an OpenAI-compatible provider in your editor:

| Setting | Value |
|---|---|
| Base URL | `http://<gpu-host>:5000/v1` on a trusted LAN/Tailscale network, or your configured HTTPS `/v1` URL |
| Model name | `gpt-4o` |

Leave the model name as **`gpt-4o`**. It is only a compatibility label that keeps editor tool support enabled; inference still runs on the local profile shown by `list models` or the Status page.

Some clients require HTTPS. The installer can configure a reverse SSH connection to a host that already has a valid certificate. Details are in the [network section of the install guide](tabbyAPI/deploy/arch/README.md#1-fresh-machine-github).

![Using help, switching models, generating an image, and building a page](docs/ide-chat.gif)

## Commands

Send commands as the entire message. For example, send `switch to qwen`, not “please switch to qwen.”

| Message | Result |
|---|---|
| `help` | Show the current in-chat user guide |
| `list models` | List installed profiles and mark the loaded one |
| `restart` | Restart the API and reload the last language model |
| `switch to qwen` | Load the everyday coding profile |
| `switch to qwen35` / `switch to qwen36` | Load a larger profile for long or difficult work |
| `switch to gemma` / `switch to gemma26` | Load a general-purpose profile |
| `switch to glm` | Load the thinking profile |
| `switch to comfy` / `switch to flux` | Unload the language model and start image generation |
| `switch to llm` | Stop ComfyUI and restore the last language model |

Only installed profiles appear in `list models`. Warm switching on an RTX 4070 Ti 12 GB ranges from about 15 seconds to 3 minutes; a first boot can take longer while Triton compiles.

## Generate images

For a single image, ask directly:

```text
generate an image of a neon diner on a rainy street at night
```

Tabby Stack moves the GPU to ComfyUI, creates the image, returns a URL from the same server, and restores the previous language model. To make several images without reloading the model between each one, use `switch to comfy`, send prompts, then `switch to qwen`.

- Flux Schnell is the default for photos, scenes, drafts, and img2img.
- Prefix a prompt with `qwen-image:` for logos, posters, interface mockups, or readable text.
- Attach a source image in the same message for Flux img2img.
- Generated files also appear in **Gallery**.

OpenAI-compatible clients can call `POST /v1/images/generations`; the response contains both `b64_json` and a server URL.

For editor agents that build pages with generated assets, see [AGENTS.md](AGENTS.md). No extra image plugin or `mcp.json` is required.

## Update

Run this on the GPU host:

```bash
bash "$HOME/tabby-stack/update.sh"
```

- **Update git** pulls code and optionally restarts the service.
- **Update all** pulls code, refreshes dependencies, restarts, and waits for health.
- `--comfy` additionally updates ComfyUI and ComfyUI-GGUF.

The same actions are available on **Status**. Updates preserve `config.yml`, `tabby.env`, model weights, and the virtual environment. They do not run a full Arch system upgrade.

## More documentation

- [Arch installation and troubleshooting](tabbyAPI/deploy/arch/README.md)
- [Editor and agent behavior](AGENTS.md)
- [Upstream TabbyAPI documentation](tabbyAPI/README.md)

## License

TabbyAPI is [AGPL-3.0](LICENSE), matching [upstream TabbyAPI](https://github.com/theroyallab/tabbyAPI). ComfyUI, custom nodes, and model weights retain their own licenses.
