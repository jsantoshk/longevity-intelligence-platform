(function () {
  const STATE = {
    folders: [],
    totalDocs: 0,
    unfiledDocs: 0,
    selectedFolder: "", // "" = all, "unfiled" = unfiled, or numeric folder id string
    page: 1,
    pageSize: 20,
    q: "",
    docs: [],
    editingFolderId: null,
  };

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function injectStyles() {
    if (document.getElementById("lip-kb-styles")) return;
    const style = document.createElement("style");
    style.id = "lip-kb-styles";
    style.textContent = `
      .lip-kb-grid { display:grid; grid-template-columns:260px 1fr; gap:16px; align-items:start; }
      @media (max-width: 900px) { .lip-kb-grid { grid-template-columns:1fr; } }
      .lip-kb-folder-item { display:flex; align-items:center; justify-content:space-between; gap:8px; padding:9px 11px; border-radius:9px; cursor:pointer; font-size:13.5px; color:#1f1635; margin-bottom:4px; border:1px solid transparent; transition:background .12s, border-color .12s; }
      .lip-kb-folder-item:hover { background:#f5f2fc; }
      .lip-kb-folder-item.active { background:#ede9fe; border-color:#d8cff7; font-weight:600; color:#4c1d95; }
      .lip-kb-count { font-size:11.5px; font-weight:600; color:#645c7a; background:#f3effa; padding:2px 8px; border-radius:999px; }
      .lip-kb-folder-item.active .lip-kb-count { background:#fff; color:#6d28d9; }
      .lip-kb-f-actions { display:flex; gap:4px; opacity:0.75; }
      .lip-kb-f-actions button { background:transparent; border:none; cursor:pointer; font-size:12px; color:#645c7a; padding:2px 4px; border-radius:4px; }
      .lip-kb-f-actions button:hover { background:#e6e1f2; color:#1f1635; }
      .lip-kb-move-sel { padding:5px 8px; border-radius:8px; border:1px solid #dfd7f5; background:#fff; font-size:12.5px; color:#1f1635; font-family:inherit; max-width:170px; }
    `;
    document.head.appendChild(style);
  }

  function mountKb() {
    const navList = document.querySelector(".nav-list");
    const firstPanel = document.querySelector(".view-panel");
    if (!navList || !firstPanel || document.getElementById("view-kb")) return;

    injectStyles();

    const btn = document.createElement("button");
    btn.className = "nav-item";
    btn.dataset.view = "kb";
    btn.textContent = "KB Folders";
    btn.onclick = () => window.switchView("kb");
    navList.appendChild(btn);

    const panel = document.createElement("section");
    panel.id = "view-kb";
    panel.className = "view-panel";
    panel.innerHTML = `
      <div class="lip-ao-header">
        <div>
          <h2 class="lip-ao-title">Knowledge Base Folder Management</h2>
          <p class="lip-ao-sub">Organize ingested documents into topic folders, search metadata, and browse 20 per page.</p>
        </div>
        <div style="display:flex;gap:8px;align-items:center;">
          <input id="lip-kb-search" class="lip-ao-input" style="width:240px;" placeholder="Search docs, city, sector..." />
          <button id="lip-kb-add-folder" class="lip-ao-btn">+ New Folder</button>
        </div>
      </div>

      <div class="lip-kb-grid">
        <div class="lip-ao-card" style="padding:12px;">
          <div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:#645c7a;margin:2px 6px 10px;">Folders</div>
          <div id="lip-kb-folder-list">Loading...</div>
        </div>

        <div class="lip-ao-card">
          <div style="display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid #ece8f5;">
            <strong id="lip-kb-active-title" style="color:#1f1635;font-size:14.5px;">All Documents</strong>
            <span id="lip-kb-active-desc" style="font-size:12.5px;color:#645c7a;"></span>
          </div>
          <table class="lip-ao-table">
            <thead>
              <tr>
                <th>Document</th>
                <th>Location / Sector</th>
                <th>Graph Entities</th>
                <th>Folder</th>
              </tr>
            </thead>
            <tbody id="lip-kb-tbody"><tr><td colspan="4">Loading...</td></tr></tbody>
          </table>
          <div class="lip-ao-pager">
            <span id="lip-kb-count"></span>
            <div style="display:flex;gap:8px;">
              <button id="lip-kb-prev" class="lip-ao-btn-ghost">Prev</button>
              <button id="lip-kb-next" class="lip-ao-btn-ghost">Next</button>
            </div>
          </div>
        </div>
      </div>

      <div id="lip-kb-modal-bg" class="lip-ao-modal-bg">
        <div class="lip-ao-modal">
          <h3 id="lip-kb-modal-title" style="margin:0 0 14px;color:#1f1635;">New Folder</h3>
          <div class="lip-ao-field">
            <label>Folder Name</label>
            <input id="lip-kb-f-name" class="lip-ao-input" placeholder="e.g. Healthy Ageing Policy" />
          </div>
          <div class="lip-ao-field">
            <label>Description</label>
            <textarea id="lip-kb-f-desc" class="lip-ao-input" rows="3" placeholder="Short description of documents in this folder..."></textarea>
          </div>
          <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:14px;">
            <button id="lip-kb-cancel" class="lip-ao-btn-ghost">Cancel</button>
            <button id="lip-kb-save" class="lip-ao-btn">Save</button>
          </div>
        </div>
      </div>
    `;
    firstPanel.parentElement.appendChild(panel);
    bindEvents();
  }

  async function loadFolders() {
    const res = await fetch("/api/admin/kb/folders");
    const data = await res.json();
    STATE.folders = data.folders || [];
    STATE.totalDocs = data.total_docs ?? 0;
    STATE.unfiledDocs = data.unfiled_docs ?? 0;
    renderFolders();
  }

  function renderFolders() {
    const list = document.getElementById("lip-kb-folder-list");
    if (!list) return;

    const fixed = [
      { id: "", name: "All Documents", count: STATE.totalDocs, system: true },
      { id: "unfiled", name: "Unfiled", count: STATE.unfiledDocs, system: true },
    ];

    const html = [
      ...fixed.map((f) => `
        <div class="lip-kb-folder-item ${STATE.selectedFolder === f.id ? "active" : ""}" data-folder-id="${f.id}">
          <span>${esc(f.name)}</span>
          <span class="lip-kb-count">${f.count}</span>
        </div>`),
      `<div style="height:1px;background:#ece8f5;margin:8px 4px;"></div>`,
      ...STATE.folders.map((f) => `
        <div class="lip-kb-folder-item ${STATE.selectedFolder === String(f.id) ? "active" : ""}" data-folder-id="${f.id}">
          <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(f.description || f.name)}">${esc(f.name)}</span>
          <div style="display:flex;align-items:center;gap:6px;flex-shrink:0;">
            <span class="lip-kb-f-actions">
              <button type="button" data-edit-folder="${f.id}" title="Edit folder">✎</button>
              <button type="button" data-del-folder="${f.id}" title="Delete folder">✕</button>
            </span>
            <span class="lip-kb-count">${f.doc_count}</span>
          </div>
        </div>`),
    ].join("");

    list.innerHTML = html;

    const titleEl = document.getElementById("lip-kb-active-title");
    const descEl = document.getElementById("lip-kb-active-desc");
    if (STATE.selectedFolder === "") {
      titleEl.textContent = "All Documents";
      descEl.textContent = `${STATE.totalDocs} total ingested`;
    } else if (STATE.selectedFolder === "unfiled") {
      titleEl.textContent = "Unfiled Documents";
      descEl.textContent = "Not yet assigned to a folder";
    } else {
      const f = STATE.folders.find((x) => String(x.id) === STATE.selectedFolder);
      titleEl.textContent = f ? f.name : "Folder";
      descEl.textContent = f?.description || "";
    }
  }

  async function loadDocs() {
    const q = encodeURIComponent(STATE.q);
    const fid = encodeURIComponent(STATE.selectedFolder);
    const res = await fetch(`/api/admin/kb/documents?page=${STATE.page}&page_size=${STATE.pageSize}&q=${q}&folder_id=${fid}`);
    const data = await res.json();
    STATE.docs = data.items || [];

    const tbody = document.getElementById("lip-kb-tbody");
    if (!STATE.docs.length) {
      tbody.innerHTML = `<tr><td colspan="4" style="color:#645c7a;padding:24px;text-align:center;">No documents in this view.</td></tr>`;
    } else {
      const folderOpts = (currentId) =>
        `<option value="" ${!currentId ? "selected" : ""}>Unfiled</option>` +
        STATE.folders.map((f) => `<option value="${f.id}" ${currentId === f.id ? "selected" : ""}>${esc(f.name)}</option>`).join("");

      tbody.innerHTML = STATE.docs.map((d) => {
        const meta = [d.city, d.country, d.sector].filter(Boolean).join(" · ") || "—";
        const entities = `${d.dimensions} dims · ${d.kpis} KPIs · ${d.interventions} ints`;
        return `
          <tr>
            <td>
              <strong>${esc(d.name)}</strong>
              <div style="font-size:11.5px;color:#645c7a;">${d.pages ?? 0} pages</div>
            </td>
            <td style="font-size:12.5px;color:#4a435e;">${esc(meta)}</td>
            <td style="font-size:12.5px;color:#4a435e;">${esc(entities)}</td>
            <td>
              <select class="lip-kb-move-sel" data-move-sha="${esc(d.sha256)}">
                ${folderOpts(d.folder_id)}
              </select>
            </td>
          </tr>`;
      }).join("");
    }

    const fromNum = data.total ? (data.page - 1) * data.page_size + 1 : 0;
    const toNum = data.total ? Math.min(data.total, data.page * data.page_size) : 0;
    document.getElementById("lip-kb-count").textContent =
      `Showing ${fromNum}–${toNum} of ${data.total} (Page ${data.page} of ${data.total_pages})`;
    document.getElementById("lip-kb-prev").disabled = data.page <= 1;
    document.getElementById("lip-kb-next").disabled = data.page >= data.total_pages;
  }

  function openFolderModal(folder) {
    STATE.editingFolderId = folder ? folder.id : null;
    document.getElementById("lip-kb-modal-title").textContent = folder ? "Edit Folder" : "New Folder";
    document.getElementById("lip-kb-f-name").value = folder?.name || "";
    document.getElementById("lip-kb-f-desc").value = folder?.description || "";
    document.getElementById("lip-kb-modal-bg").classList.add("open");
  }

  function bindEvents() {
    document.getElementById("lip-kb-search").oninput = (e) => {
      STATE.q = e.target.value;
      STATE.page = 1;
      loadDocs();
    };
    document.getElementById("lip-kb-prev").onclick = () => { if (STATE.page > 1) { STATE.page--; loadDocs(); } };
    document.getElementById("lip-kb-next").onclick = () => { STATE.page++; loadDocs(); };
    document.getElementById("lip-kb-add-folder").onclick = () => openFolderModal(null);
    document.getElementById("lip-kb-cancel").onclick = () => document.getElementById("lip-kb-modal-bg").classList.remove("open");

    document.getElementById("lip-kb-save").onclick = async () => {
      const payload = {
        name: document.getElementById("lip-kb-f-name").value.trim(),
        description: document.getElementById("lip-kb-f-desc").value.trim(),
      };
      if (!payload.name) return alert("Folder name is required");
      const url = STATE.editingFolderId ? `/api/admin/kb/folders/${STATE.editingFolderId}` : "/api/admin/kb/folders";
      const method = STATE.editingFolderId ? "PUT" : "POST";
      const res = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        return alert(err.detail || "Save failed");
      }
      document.getElementById("lip-kb-modal-bg").classList.remove("open");
      await loadFolders();
      await loadDocs();
    };

    document.getElementById("lip-kb-folder-list").onclick = async (e) => {
      const editId = e.target.dataset.editFolder;
      const delId = e.target.dataset.delFolder;
      if (editId) {
        e.stopPropagation();
        const f = STATE.folders.find((x) => String(x.id) === editId);
        if (f) openFolderModal(f);
        return;
      }
      if (delId) {
        e.stopPropagation();
        if (!confirm("Delete this folder? Documents inside will move to Unfiled.")) return;
        await fetch(`/api/admin/kb/folders/${delId}`, { method: "DELETE" });
        if (STATE.selectedFolder === delId) STATE.selectedFolder = "";
        await loadFolders();
        await loadDocs();
        return;
      }
      const item = e.target.closest("[data-folder-id]");
      if (!item) return;
      STATE.selectedFolder = item.dataset.folderId;
      STATE.page = 1;
      renderFolders();
      loadDocs();
    };

    document.getElementById("lip-kb-tbody").onchange = async (e) => {
      const sha = e.target.dataset.moveSha;
      if (!sha) return;
      const val = e.target.value;
      await fetch(`/api/admin/kb/documents/${encodeURIComponent(sha)}/folder`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ folder_id: val ? Number(val) : null }),
      });
      await loadFolders();
      await loadDocs();
    };
  }

  function hookSwitchView() {
    const orig = window.switchView;
    if (typeof orig !== "function") return;
    window.switchView = function (view) {
      orig(view);
      if (view === "kb") {
        loadFolders().then(loadDocs);
      }
    };
  }

  function init() {
    mountKb();
    hookSwitchView();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();