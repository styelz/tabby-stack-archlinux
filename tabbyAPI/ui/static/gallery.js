function mountGallery(root) {
  root.innerHTML = `
    <div class="toolbar">
      <span id="sel-count">0 selected</span>
      <button class="btn" id="del-sel" disabled>Delete selected</button>
      <button class="btn danger" id="del-all">Delete all</button>
      <span class="spacer"></span>
      <div class="pager" id="pager"></div>
    </div>
    <div class="grid" id="grid"></div>
    <p class="error" id="gallery-error" hidden></p>
    <div class="modal" id="modal">
      <div class="modal-inner">
        <img alt="" />
        <div class="modal-bar">
          <span class="modal-name" id="modal-name"></span>
          <a class="btn" id="modal-open" target="_blank" rel="noreferrer">Open original</a>
          <span class="muted">Esc closes</span>
        </div>
      </div>
    </div>
  `;
  const grid = root.querySelector("#grid");
  const pager = root.querySelector("#pager");
  const count = root.querySelector("#sel-count");
  const delSel = root.querySelector("#del-sel");
  const errorEl = root.querySelector("#gallery-error");
  const modal = root.querySelector("#modal");
  const modalImg = modal.querySelector("img");
  const modalName = root.querySelector("#modal-name");
  const modalOpen = root.querySelector("#modal-open");

  function showError(message) {
    errorEl.hidden = !message;
    errorEl.textContent = message || "";
  }
  let page = 1;
  let lastIndex = 0;
  let boxes = [];
  let kept = new Set();
  let isAdmin = false;
  TabbyUI.api("auth/check")
    .then((data) => {
      isAdmin = Boolean(data.is_admin);
    })
    .catch(() => {});

  function selected() {
    return boxes
      .filter((box) => box.checked)
      .map((box) => box.closest("figure")?.dataset.name)
      .filter(Boolean);
  }

  function paint() {
    boxes.forEach((box) => {
      const fig = box.closest("figure");
      if (fig) fig.classList.toggle("is-on", box.checked);
    });
    const n = selected().length;
    count.textContent = `${n} selected`;
    delSel.disabled = !n;
  }

  function snapshot() {
    kept = new Set(selected());
  }

  function restore() {
    boxes.forEach((box) => {
      const name = box.closest("figure")?.dataset.name;
      box.checked = Boolean(name && kept.has(name));
    });
  }

  function bindBoxes() {
    boxes = Array.from(grid.querySelectorAll(".pick input"));
  }

  function applyRange(from, to, checked) {
    const a = Math.min(from, to);
    const z = Math.max(from, to);
    for (let j = a; j <= z; j += 1) {
      if (boxes[j]) boxes[j].checked = checked;
    }
    paint();
  }

  grid.addEventListener("click", (event) => {
    const pick = event.target.closest(".pick");
    if (!pick || !grid.contains(pick)) return;
    const i = Number(pick.closest("figure")?.dataset.index);
    if (!Number.isInteger(i) || !boxes[i]) return;
    if (event.shiftKey) {
      const from = lastIndex;
      // The browser toggles the clicked box before this handler. That
      // new state is the range action (tick or untick). preventDefault
      // then undoes the single toggle; re-apply it across the range.
      const checked = boxes[i].checked;
      event.preventDefault();
      setTimeout(() => applyRange(from, i, checked), 0);
      return;
    }
    lastIndex = i;
  });
  grid.addEventListener("change", (event) => {
    if (event.target.matches(".pick input")) paint();
  });

  async function load(nextPage) {
    snapshot();
    const target = nextPage || 1;
    if (target !== page) lastIndex = 0;
    page = target;
    showError("");
    const data = await TabbyUI.api(`gallery/list?page=${page}&per_page=24`);
    if (!Array.isArray(data.items) || !data.items.length) {
      grid.innerHTML = "<p class='muted'>No generated images yet.</p>";
      pager.innerHTML = "";
      boxes = [];
      paint();
      return;
    }
    grid.innerHTML = data.items
      .map((item, index) => {
        const url = TabbyUI.resolveUiUrl(item.url);
        const thumb = TabbyUI.resolveUiUrl(item.thumb);
        const name = TabbyUI.escapeHtml(item.name);
        return `
        <figure class="shot" data-name="${name}" data-index="${index}">
          <label class="pick" title="Select">
            <input type="checkbox" aria-label="Select ${name}" />
          </label>
          <a class="open" href="${url}" data-full="${url}">
            <img src="${thumb}" alt="${name}" loading="lazy" />
          </a>
          <figcaption>${name}${item.owner ? " · " + TabbyUI.escapeHtml(item.owner) : ""}<br>${TabbyUI.escapeHtml(item.mtime)} · ${TabbyUI.formatBytes(item.size)}</figcaption>
        </figure>`;
      })
      .join("");
    bindBoxes();
    restore();
    const links = [];
    for (let n = 1; n <= data.pages; n += 1) {
      links.push(
        n === data.page
          ? `<span class="btn is-current" aria-current="page">${n}</span>`
          : `<button type="button" class="btn" data-page="${n}">${n}</button>`
      );
    }
    pager.innerHTML = `Page ${data.page} / ${data.pages} · ${data.total} images ` + links.join("");
    pager.querySelectorAll("button[data-page]").forEach((btn) => {
      btn.addEventListener("click", () => load(Number(btn.dataset.page)));
    });
    paint();
  }

  function closeModal() {
    if (!modal.classList.contains("is-open")) return;
    modal.classList.remove("is-open");
    modalImg.removeAttribute("src");
  }

  function imageUrl(fig) {
    const link = fig && fig.querySelector("a.open");
    return (link && (link.dataset.full || link.href)) || "";
  }

  function downloadNamed(url, name) {
    const link = document.createElement("a");
    link.href = url;
    link.download = name || "image.png";
    link.rel = "noreferrer";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  async function deleteNames(names) {
    if (!names.length) return;
    const yes = await TabbyUI.confirmModal({
      title: "Delete images",
      text: `Delete ${names.length} image(s)?`,
      yes: "Delete",
      no: "Cancel",
    });
    if (!yes) return;
    try {
      await TabbyUI.api("gallery/delete", { method: "POST", body: { names } });
      await load(page);
    } catch (err) {
      showError(err.message);
    }
  }

  grid.addEventListener("contextmenu", (event) => {
    const fig = event.target.closest("figure.shot");
    if (!fig || !grid.contains(fig)) return;
    const name = fig.dataset.name || "";
    const url = imageUrl(fig);
    const box = fig.querySelector(".pick input");
    const on = Boolean(box && box.checked);
    TabbyUI.showContextMenu(event, [
      { label: "Open", run: () => {
        modalImg.src = url;
        modalName.textContent = name;
        modalOpen.href = url;
        modal.classList.add("is-open");
      } },
      { label: "Open original", run: () => window.open(url, "_blank", "noreferrer") },
      { label: "Copy URL", run: () => TabbyUI.copyText(url) },
      { label: "Copy name", run: () => TabbyUI.copyText(name) },
      { label: "Download", run: () => downloadNamed(url, name) },
      { sep: true },
      { label: on ? "Deselect" : "Select", run: () => {
        if (!box) return;
        box.checked = !on;
        lastIndex = Number(fig.dataset.index) || lastIndex;
        paint();
      } },
      { label: "Delete", danger: true, run: () => deleteNames([name]) },
    ]);
  });

  modal.addEventListener("contextmenu", (event) => {
    if (!modal.classList.contains("is-open")) return;
    const name = modalName.textContent || "";
    const url = modalImg.getAttribute("src") || modalOpen.href || "";
    if (!url) return;
    TabbyUI.showContextMenu(event, [
      { label: "Open original", run: () => window.open(url, "_blank", "noreferrer") },
      { label: "Copy URL", run: () => TabbyUI.copyText(url) },
      { label: "Copy name", run: () => TabbyUI.copyText(name) },
      { label: "Download", run: () => downloadNamed(url, name) },
      { sep: true },
      { label: "Close", run: () => closeModal() },
    ]);
  });

  grid.addEventListener("click", (event) => {
    if (event.target.closest(".pick")) return;
    const link = event.target.closest("a.open");
    if (!link) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    const name = link.closest("figure")?.dataset.name || "";
    modalImg.src = link.dataset.full;
    modalName.textContent = name;
    modalOpen.href = link.dataset.full;
    modal.classList.add("is-open");
  });
  modal.addEventListener("click", (event) => {
    if (event.target.closest("#modal-open")) return;
    closeModal();
  });
  function onKey(event) {
    if (event.key === "Escape") closeModal();
  }
  document.addEventListener("keydown", onKey);
  delSel.addEventListener("click", async () => {
    const names = selected();
    if (!names.length) return;
    const yes = await TabbyUI.confirmModal({
      title: "Delete images",
      text: `Delete ${names.length} image(s)?`,
      yes: "Delete",
      no: "Cancel",
    });
    if (!yes) return;
    try {
      await TabbyUI.api("gallery/delete", { method: "POST", body: { names } });
      await load(page);
    } catch (err) {
      showError(err.message);
    }
  });
  root.querySelector("#del-all").addEventListener("click", async () => {
    const yes = await TabbyUI.confirmModal({
      title: "Delete all images",
      text: isAdmin ? "Delete ALL generated images?" : "Delete all of your images?",
      yes: "Delete all",
      no: "Cancel",
    });
    if (!yes) return;
    try {
      await TabbyUI.api("gallery/delete", { method: "POST", body: { all: true } });
      await load(1);
    } catch (err) {
      showError(err.message);
    }
  });

  load(1).catch((err) => {
    grid.innerHTML = "";
    showError(err.message);
  });
  return {
    pause() {
      closeModal();
    },
    resume() {
      load(page).catch((err) => showError(err.message));
    },
    destroy() {
      document.removeEventListener("keydown", onKey);
    },
  };
}

window.mountGallery = mountGallery;
