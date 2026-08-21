# Agent / IDE notes (tabby-stack)

Use **gpt-4o** as the model name in your editor, and leave it. That is not ChatGPT — it is only a name. Many editors sandbox or block tools unless they see a known OpenAI name. The GPU still runs the local model you switched to.

This file is for **any** editor that talks to the TabbyAPI server (Cursor, VS Code, Continue, Cline, Roo, JetBrains with an OpenAI-compatible plugin, plain HTTP clients, and so on). The coding workspace is a different computer. Treat this API like OpenAI: chat and HTTP only.

## API

- Base URL: the `/v1` URL you configured in the IDE (LAN, Tailscale, or a tunnel)
- Model name: **`gpt-4o`** (leave it)
- Health: `GET /health` on the same origin

Do not touch the GPU host to change models. Send a chat phrase instead. Send `restart` to bounce the API.

## Switch models

Send a message that is **only** one of these. Times are warm switches on this RTX 4070 Ti 12 GB (first boot can compile Triton longer). Chat replies use `tabbyAPI/model_profiles/switch_times.json`.

| Phrase | Use | Context | Ready |
|---|---|---|---|
| `help` | Full usage guide | — | — |
| `list models` | Show installed profiles | — | — |
| `restart` | Bounce the API; last model reloads | — | ~65 seconds |
| `switch to qwen` | Daily coding, 9B | 262k | ~65 seconds |
| `switch to qwen35` | Long or hard agent work | 196k | ~3 minutes |
| `switch to qwen36` | Long or hard agent work | 131k | ~85 seconds |
| `switch to gemma` | General | 262k | ~65 seconds |
| `switch to gemma26` | General | 262k | ~2 minutes |
| `switch to glm` | Thinking (vision off on RTX 4070 Ti 12 GB) | 65k (model max) | ~15 seconds |
| `switch to comfy` / `flux` | Unload the LLM; image gen | — | ~35 seconds (then Flux ~3 minutes / Qwen-Image ~4 minutes for the first picture) |
| `switch to llm` | Free Comfy; reload the last LLM | — | ~65 seconds |

The GPU is exclusive: **LLM or Comfy, not both**. `Qwen3-Embedding-0.6B` stays on CPU (`POST /v1/embeddings`). After `switch to comfy`, Flux Schnell is for drafts; Qwen-Image is for text / posters / UI, or a `qwen-image:` prefix.

## Images (works in every IDE)

The GPU server generates the PNG and returns a URL on **this same API host**. No special IDE plugin is required.

- In chat: send `switch to comfy`, wait until Comfy is ready, then describe the image. Flux Schnell is the default draft. Prefix `qwen-image:` (or mention poster / button / logo) for readable text. Hero/header photos: describe a scene, not a website. Paste a photo in the same turn for Flux img2img. Then `switch to qwen`.
- Or one line while coding: `generate an image of a login form`. The API hands the GPU to Comfy, returns the URL, and reloads the last LLM.
- Or OpenAI-shaped (portable; use this from VS Code, Continue, scripts, etc.):

```bash
curl -sS -X POST "$TABBY_V1/images/generations" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"qwen-image: a logo that says Cafe"}'
```

Returns `b64_json` and `url`. Save the PNG into the project with a shell command (decode `b64_json`, or download the `url`). Do not paste binary into chat. Never use a built-in cloud “generate image”. Never open a browser to POST JSON.

### Coding plus images (same chat)

A line like “create a webpage and generate a header and logo” is a **coding task**. The API plans the PNG dests and **starts the Comfy job itself**. Do not turn it into React/Vite boilerplate or SVG/CSS/Pillow art unless the user asked for those.

1. Keep using the wait or download tool this API requests (Shell `sleep`/`ls`, then `curl` when the job is done). Do not invent `/v1/images/generated-*.png` URLs. A queued or backgrounded command is not success.
2. After those PNG files exist on disk: save HTML/CSS/JS with the editor’s file tools. Do not dump the page in chat. Point `img src` at the planned local paths such as `images/logo.png`.
3. Prefix `qwen-image:` for logos and readable text. Hero/header photos: describe a scene, not a website. Flux draft about 3 minutes each, Qwen-Image about 4 minutes each, then about 65 seconds to reload the coding model once.

Text editors cannot save PNG bytes. Several PNGs share one Comfy batch.

## Long tasks

- Daily work: stay on `qwen`. For a long agent job, switch to `qwen35` or `qwen36` first, then continue in a new chat.
- Split big work: explore and stop, then a second chat that only makes the edit.
- Do not repeat the same search with the same arguments. After about 8 search/read rounds with no edit, stop and say what you found.
