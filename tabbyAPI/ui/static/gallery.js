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
    <div class="modal" id="modal">
      <img alt="" />
    </div>
  `;
  const grid = root.querySelector("#grid");
  const pager = root.querySelector("#pager");
  const count = root.querySelector("#sel-count");
  const delSel = root.querySelector("#del-sel");
  const modal = root.querySelector("#modal");
  const modalImg = modal.querySelector("img");
  let page = 1;
  let lastIndex = 0;
  let boxes = [];
  let kept = new Set();

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

  function applyPick(event, i) {
    if (event.shiftKey) {
      const a = Math.min(lastIndex, i);
      const z = Math.max(lastIndex, i);
      for (let j = a; j <= z; j += 1) {
        if (boxes[j]) boxes[j].checked = true;
      }
    } else {
      boxes[i].checked = !boxes[i].checked;
      lastIndex = i;
    }
    paint();
  }

  grid.addEventListener(
    "click",
    (event) => {
      const pick = event.target.closest(".pick");
      if (!pick || !grid.contains(pick)) return;
      const i = Number(pick.closest("figure")?.dataset.index);
      if (!Number.isInteger(i) || !boxes[i]) return;
      event.preventDefault();
      event.stopPropagation();
      applyPick(event, i);
    },
    true
  );
  grid.addEventListener("change", (event) => {
    if (event.target.matches(".pick input")) paint();
  });

  async function load(nextPage) {
    snapshot();
    const target = nextPage || 1;
    if (target !== page) lastIndex = 0;
    page = target;
    const data = await TabbyUI.api(`gallery/list?page=${page}&per_page=24`);
    if (!data.items.length) {
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
          ? `<span class="btn" disabled>${n}</span>`
          : `<button type="button" class="btn" data-page="${n}">${n}</button>`
      );
    }
    pager.innerHTML = `Page ${data.page} / ${data.pages} · ${data.total} images ` + links.join("");
    pager.querySelectorAll("button[data-page]").forEach((btn) => {
      btn.addEventListener("click", () => load(Number(btn.dataset.page)));
    });
    paint();
  }

  grid.addEventListener("click", (event) => {
    if (event.target.closest(".pick")) return;
    const link = event.target.closest("a.open");
    if (!link) return;
    event.preventDefault();
    modalImg.src = link.dataset.full;
    modal.classList.add("is-open");
  });
  modal.addEventListener("click", () => {
    modal.classList.remove("is-open");
    modalImg.removeAttribute("src");
  });
  delSel.addEventListener("click", async () => {
    const names = selected();
    if (!names.length || !confirm(`Delete ${names.length} image(s)?`)) return;
    await TabbyUI.api("gallery/delete", { method: "POST", body: { names } });
    await load(page);
  });
  root.querySelector("#del-all").addEventListener("click", async () => {
    if (!confirm("Delete ALL generated images?")) return;
    await TabbyUI.api("gallery/delete", { method: "POST", body: { all: true } });
    await load(1);
  });

  load(1).catch((err) => {
    grid.innerHTML = `<p class="error">${TabbyUI.escapeHtml(err.message)}</p>`;
  });
  return {
    resume() {
      load(page).catch(() => {});
    },
    destroy() {},
  };
}

window.mountGallery = mountGallery;
