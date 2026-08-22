# Arch Linux install

Use **gpt-4o** as the model name in your editor, and leave it. That is not ChatGPT — it is only a name. Many editors sandbox or block tools unless they see a known OpenAI name. The GPU still runs the local model you switched to.

The git tree is **code only**. It does not ship LLMs, Flux, or Qwen-Image weights. `install.sh` copies a file from an optional local cache if that file already exists, otherwise it downloads it from Hugging Face. Re-run skips anything already on disk.

Stack overview lives in the [repository root README](../../../README.md).

After install you do not need this chat. The same how-to is written to `HOW-TO-ARCH.txt` next to TabbyAPI. Command output from the work phase is in `$DEST/tabby-install.log`.

## 1. Fresh machine (GitHub)

Needs Arch Linux, an NVIDIA GPU, and internet. Run as **your user**, not root.

```bash
sudo pacman -S --needed git
git clone https://github.com/styelz/tabby-stack-archlinux.git
cd tabby-stack-archlinux
bash install.sh
```

The installer is a how-to as well as a script. On a terminal it uses **dialog** (ncurses menus). If `dialog` is missing it installs it, or falls back to printed questions. Each screen explains what is needed and gives examples. Esc cancels. After you confirm, the work phase shows a **progress bar** only; full output goes to `$DEST/tabby-install.log`. Set `TABBY_INSTALL_VERBOSE=1` to print every command.

You will be asked:

1. **Arch install root** — Linux disk, default `$HOME/tabby-stack` (TabbyAPI and ComfyUI go underneath). Not a USB or other removable mount.
2. **Weights cache** — Hugging Face, USB, or a custom path
3. **Model set** — `core` (qwen 9B + Flux + Qwen-Image + embedder) or `all` (every `switch to …` profile)
4. **Listen URLs** — TabbyAPI host/port and ComfyUI URL (defaults `127.0.0.1:5000` and `http://127.0.0.1:8188`)
5. **Public URL / tunnel** — optional public API base, SSH remote, forward spec, and key
6. **Confirm** — review paths and URLs before anything is installed

Non-interactive (no menus):

```bash
TABBY_INSTALL_ROOT="$HOME/tabby-stack" TABBY_CACHE="" TABBY_MODELS=core \
  TABBY_NETWORK_HOST=127.0.0.1 TABBY_NETWORK_PORT=5000 \
  COMFYUI_URL=http://127.0.0.1:8188 \
  TABBY_PUBLIC_BASE="" TABBY_SSH_REMOTE="" \
  bash install.sh
```

Or `TABBY_NONINTERACTIVE=1` with the same variables.

Gemma downloads may be gated. If Hugging Face returns 401/403: `huggingface-cli login` or `export HF_TOKEN=...`.

## 2. Optional: reuse weights you already have

If a USB copy of this tree (or another folder with the model weights) is mounted, point the cache at it. Existing folders are copied; missing ones still download.

```bash
sudo pacman -S --needed ntfs-3g
sudo mkdir -p /mnt/usb
sudo mount /dev/sdXN /mnt/usb
# You should see /mnt/usb/tabby-stack/tabbyAPI

bash install.sh
# Weights cache = /mnt/usb/tabby-stack
```

Do not reuse Windows `venv` folders.

Catalog of Hugging Face repos: [`models.json`](models.json).

It will:

- Install `sudo` if missing (asks for the root password once) and add your user
- Install pacman packages (NVIDIA userspace, git, rsync, openssh, build tools, `dos2unix`, image/FFmpeg libs)
- Install **Python 3.12** via pyenv 3.12.5 if `python3.12` is not on PATH (does not use system 3.13/3.14)
- Skip any weight that already exists; copy from the cache if present; otherwise download
- Clone **ComfyUI** and **ComfyUI-GGUF**
- Install Tabby **extras**, pin **numpy ≥ 2.1**, and keep **Qwen3-Embedding-0.6B** on CPU
- Create Linux venvs and `pip install .[cu12]` plus ComfyUI + CUDA Torch
- Patch Linux spawn / chat-switch so `switch to …` does not 500 or look like Comfy
- Set the startup model to **qwen 9B** and `embedding_model_name` to **Qwen3-Embedding-0.6B**
- Enable **linger** + `tabbyapi` so it **starts at boot with no login**
- If a newly installed NVIDIA driver does not load, reboot once and resume automatically
- Write `$DEST/start.sh` at the install root
- Write `$DEST/AGENTS.md` (IDE / agent notes for any editor)
- Write `HOW-TO-ARCH.txt`

It does **not** install the full `cuda` toolkit. Torch and ExLlamaV3 wheels already include CUDA 12.8.

It uses **Python 3.12 only**. Official Arch `python` is 3.14, and `python312` is AUR-only, so if `python3.12` is missing it installs **pyenv 3.12.5** (same workaround as the first Arch boot). It will not use system 3.13/3.14.

Fresh Arch often has **no sudo**. Run as your user (not root). The script asks for the root password once, installs `sudo`, and adds your user.

On a 4070 Ti it uses `nvidia-open` only if `nvidia-smi` is missing; it will not install both `nvidia` and `nvidia-open`.

If you mounted a USB cache you can unmount it after a successful install.

If this was the first NVIDIA driver install, **reboot once**. Linger will start TabbyAPI at boot; you do not need to log in.

## 3. Start TabbyAPI

The installer enables **linger** and `tabbyapi`. After a reboot it starts **without a login**. Check: `loginctl show-user $USER -p Linger` should be `yes`.

You only need these if linger was not set or you stopped the unit:

```bash
sudo loginctl enable-linger "$USER"
systemctl --user enable --now tabbyapi
systemctl --user status tabbyapi
```

- API: `http://127.0.0.1:5000`
- Health: `GET /health` on that origin
- OpenAI-compatible base URL for remote IDEs: `http://<gpu-host>:5000/v1` (model name **`gpt-4o`** — leave it)
- Agent / IDE notes: `$HOME/tabby-stack/AGENTS.md` (copied by the installer)
- A public reverse tunnel is optional. Set `TABBY_PUBLIC_BASE` and `TABBY_SSH_REMOTE` in `deploy/arch/tabby.env` if you have one. Every env key is listed in [`tabby.env.example`](tabby.env.example).

Do **not** run `start.bat`. On Arch use the unit above or `$HOME/tabby-stack/start.sh` at the install root.

Stop:

```bash
systemctl --user stop tabbyapi
```

Logs:

```bash
journalctl --user -u tabbyapi -f
```

Manual start (same as the unit):

```bash
/path/to/tabbyAPI/venv/bin/python /path/to/tabbyAPI/watch_api.py
```

## 4. IDE / agents

Same notes are in `$HOME/tabby-stack/AGENTS.md` (any editor, not Cursor-only).

- OpenAI-compatible base URL for remote IDEs: `http://<gpu-host>:5000/v1`
- Model name: **`gpt-4o`** (leave it — see the top of this file)
- After `switch to …`, wait for the GPU (warm RTX 4070 Ti 12 GB: qwen / gemma ~65s, qwen36 ~85s, gemma26 ~2 min, qwen35 ~3 min, glm ~15s). After `switch to comfy`, wait about **35 seconds** (first Flux ~3 min, first Qwen-Image ~4 min). GLM is thinking-only on RTX 4070 Ti 12 GB (vision off).

Chat phrases (send as the whole message):

| Phrase | What it does |
|---|---|
| `help` | Full usage guide |
| `list models` | Show installed profiles |
| `restart` | Bounce the API; last model reloads |
| `switch to qwen` | Daily coding, 9B, faster |
| `switch to qwen35` / `qwen36` | Long or hard Agent work (slower on 12 GB) |
| `switch to gemma` / `gemma26` | General |
| `switch to glm` | Thinking (vision off on 12 GB) |
| `switch to comfy` / `flux` | Unload the LLM, Comfy image gen |
| `switch to llm` | Free Comfy, reload the last LLM |

The 12 GB GPU is exclusive: **LLM or Comfy, not both**. `Qwen3-Embedding-0.6B` stays on CPU and does not need a switch. Clients switch with the chat phrases above, not a shell on the GPU host.

A short chat like `hello` is slow on `qwen35` because Cursor still sends the whole Agent prompt. Use `qwen` for daily chat.

## 5. Images (Comfy)

Coding machines are remote. The GPU server generates the PNG and returns a URL on the same API host your editor or IDE already uses. Chat phrases and `POST /v1/images/generations` work in **any** editor — no MCP required.

1. `switch to comfy`, wait ~35 seconds, then describe the image
2. Or one line: `generate an image of a red bicycle` (API hands off the GPU, returns a URL, reloads the last LLM)
3. Or `POST /v1/images/generations` with `{"prompt":"..."}` (`b64_json` + `url`) — use this from VS Code, Continue, Cline, scripts, etc.
4. A page plus pictures: the API starts the image job from the user line. No `mcp.json` is required.
5. Flux Schnell drafts: `cartoon style`, `a red bicycle in the rain` (first picture ~3 min)
6. Qwen-Image (readable text): `a poster with the heading SALE`, or `qwen-image: login form with Submit` (first picture ~4 min)
7. Paste a photo in the same turn for Flux img2img
8. `switch to qwen` when you want the coding model back (~65s)

Set `TABBY_PUBLIC_BASE` if image URLs must use a tunnel hostname. Otherwise the reply uses the Host the client already called.

Embeddings stay on CPU: `POST /v1/embeddings` with `Qwen3-Embedding-0.6B`. Do not switch to comfy for repo search.

## 6. If something fails

| Problem | What to do |
|---|---|
| `nvidia-smi` fails after a new driver | The installer reboots once and resumes with your saved answers. If it still fails after that: `nvidia-smi` and `journalctl -k \| grep -i nvidia` |
| USB NTFS read-only / dirty | `sudo ntfsfix /dev/sdXN` then remount |
| Missing model folder | Re-run `install.sh`. It downloads from Hugging Face and skips files that already exist. |
| Hugging Face 401/403 | Gated repo. `huggingface-cli login` or `export HF_TOKEN=...` then re-run. |
| SSH key missing | Optional. Only needed if you set up your own public reverse tunnel. |
| SSH rejects a cache-copied key | Windows CRLF. The installer runs `dos2unix`. Manual: `sudo pacman -S dos2unix && dos2unix ~/.ssh/id_ed25519` |
| `systemctl --user` fails | Log in graphically or `export XDG_RUNTIME_DIR=/run/user/$(id -u)` |
| Tabby dies when you log out of the shell | User units need linger. `sudo loginctl enable-linger $USER` then `loginctl show-user $USER -p Linger` should be `yes` |
| No sudo / not in wheel | Re-run as your user; enter the root password when asked. Or: `su -c 'pacman -S sudo && usermod -aG wheel USER'` |
| System Python is 3.13/3.14 | Expected. Re-run `install.sh` — it installs pyenv 3.12.5. Do not `pacman -S python312` (not in official repos). |
| Interrupted download | Re-run `install.sh`; finished files are skipped |
| Chat `switch to …` returns 500 / `creationflags is only supported on Windows` | Re-run `install.sh` (it patches the spawn), then `systemctl --user restart tabbyapi` |
| Reply says `ComfyUI is not running` after a chat or `switch to qwen` | That was a missing LLM, not Flux. Re-run `install.sh` (it now defaults to qwen 9B), then `systemctl --user restart tabbyapi` and wait ~65s |
| First start hangs / no `:5000` | Model is loading before the port opens. qwen ~65s; qwen35 ~3 min. First Linux boot may compile Triton. |

Re-run is safe: it skips a venv that already imports CUDA + ExLlamaV3.
