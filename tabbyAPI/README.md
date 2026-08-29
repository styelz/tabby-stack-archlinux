# TabbyAPI (tabby-stack-archlinux)

This directory is the customized [TabbyAPI](https://github.com/theroyallab/tabbyAPI) tree used by **tabby-stack-archlinux**.

Install from the **repository root**, not from here:

```bash
git clone https://github.com/styelz/tabby-stack-archlinux.git "$HOME/tabby-stack"
cd "$HOME/tabby-stack"
bash install.sh
```

Stack overview, chat phrases, two clients (editor `/v1` vs browser IDE), and what is not in the repo: **[../README.md](../README.md)**.

Arch steps and troubleshooting: [deploy/arch/README.md](deploy/arch/README.md). Hugging Face catalog: [deploy/arch/models.json](deploy/arch/models.json).

This tree is AGPL-3.0, same as [upstream TabbyAPI](https://github.com/theroyallab/tabbyAPI). ComfyUI and model weights have their own licenses.
