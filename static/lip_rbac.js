(function () {
  const STATE = {
    tab: "users", // users | agents | personas
    page: 1,
    pageSize: 6,
    q: "",
    items: [],
    personasCache: [],
    editingId: null,
  };

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function mountRbac() {
    const navList = document.querySelector(".nav-list");
    const firstPanel = document.querySelector(".view-panel");
    if (!navList || !firstPanel || document.getElementById("view-rbac")) return;

    const btn = document.createElement("button");
    btn.className = "nav-item";
    btn.dataset.view = "rbac";
    btn.textContent = "Roles & Agents";
    btn.onclick = () => window.switchView("rbac");
    navList.appendChild(btn);

    const panel = document.createElement("section");
    panel.id = "view-rbac";
    panel.className = "view-panel";
    panel.innerHTML = `
      <div class="lip-ao-header">
        <div>
          <h2 class="lip-ao-title">Role &amp; Authorization Management</h2>
          <p class="lip-ao-sub">Manage platform users, AI agents, and reusable persona instructions.</p>
        </div>
        <div style="display:flex;gap:8px;align-items:center;">
          <input id="lip-rbac-search" class="lip-ao-input" style="width:220px;" placeholder="Search..." />
          <button id="lip-rbac-add" class="lip-ao-btn">+ New User</button>
        </div>
      </div>
      <div class="lip-omni-tabs" id="lip-rbac-tabs">
        <button class="lip-omni-tab active" data-tab="users">Users</button>
        <button class="lip-omni-tab" data-tab="agents">Agents</button>
        <button class="lip-omni-tab" data-tab="personas">Agent Personas</button>
      </div>
      <div class="lip-ao-card">
        <table class="lip-ao-table">
          <thead id="lip-rbac-thead"></thead>
          <tbody id="lip-rbac-tbody"><tr><td colspan="5">Loading...</td></tr></tbody>
        </table>
        <div class="lip-ao-pager">
          <span id="lip-rbac-count"></span>
          <div style="display:flex;gap:8px;">
            <button id="lip-rbac-prev" class="lip-ao-btn-ghost">Prev</button>
            <button id="lip-rbac-next" class="lip-ao-btn-ghost">Next</button>
          </div>
        </div>
      </div>
      <div id="lip-rbac-modal-bg" class="lip-ao-modal-bg">
        <div class="lip-ao-modal">
          <h3 id="lip-rbac-modal-title" style="margin:0 0 14px;color:#1f1635;">New Item</h3>
          <div id="lip-rbac-modal-fields"></div>
          <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:14px;">
            <button id="lip-rbac-cancel" class="lip-ao-btn-ghost">Cancel</button>
            <button id="lip-rbac-save" class="lip-ao-btn">Save</button>
          </div>
        </div>
      </div>
    `;
    firstPanel.parentElement.appendChild(panel);
    bindEvents();
  }

  async function refreshPersonasCache() {
    const res = await fetch("/api/admin/personas?page=1&page_size=100");
    const data = await res.json();
    STATE.personasCache = data.items || [];
  }

  async function loadRbac() {
    const addLabels = { users: "+ New User", agents: "+ New Agent", personas: "+ New Persona" };
    document.getElementById("lip-rbac-add").textContent = addLabels[STATE.tab];

    const q = encodeURIComponent(STATE.q);
    const res = await fetch(`/api/admin/${STATE.tab}?page=${STATE.page}&page_size=${STATE.pageSize}&q=${q}`);
    const data = await res.json();
    STATE.items = data.items || [];

    const thead = document.getElementById("lip-rbac-thead");
    const tbody = document.getElementById("lip-rbac-tbody");

    if (STATE.tab === "users") {
      thead.innerHTML = `<tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Actions</th></tr>`;
      tbody.innerHTML = STATE.items.length
        ? STATE.items.map((u) => `
          <tr>
            <td><strong>${esc(u.name)}</strong></td>
            <td>${esc(u.email)}</td>
            <td><span class="lip-ao-badge">${esc(u.role)}</span></td>
            <td>${esc(u.status)}</td>
            <td style="white-space:nowrap;">
              <button class="lip-ao-btn-ghost" data-edit-id="${u.id}">Edit</button>
              <button class="lip-ao-btn-danger" data-del-id="${u.id}">Delete</button>
            </td>
          </tr>`).join("")
        : `<tr><td colspan="5" style="color:#645c7a;">No users found.</td></tr>`;
    } else if (STATE.tab === "agents") {
      thead.innerHTML = `<tr><th>Agent Name</th><th>Model</th><th>Persona</th><th>Status</th><th>Actions</th></tr>`;
      tbody.innerHTML = STATE.items.length
        ? STATE.items.map((a) => `
          <tr>
            <td><strong>${esc(a.name)}</strong></td>
            <td><code>${esc(a.model)}</code></td>
            <td>${esc(a.persona_name || "Unassigned")}</td>
            <td><span class="lip-ao-badge">${esc(a.status)}</span></td>
            <td style="white-space:nowrap;">
              <button class="lip-ao-btn-ghost" data-edit-id="${a.id}">Edit</button>
              <button class="lip-ao-btn-danger" data-del-id="${a.id}">Delete</button>
            </td>
          </tr>`).join("")
        : `<tr><td colspan="5" style="color:#645c7a;">No agents found.</td></tr>`;
    } else {
      thead.innerHTML = `<tr><th>Persona Name</th><th>Tone</th><th>System Instructions</th><th>Actions</th></tr>`;
      tbody.innerHTML = STATE.items.length
        ? STATE.items.map((p) => `
          <tr>
            <td><strong>${esc(p.name)}</strong></td>
            <td><span class="lip-ao-badge">${esc(p.tone)}</span></td>
            <td>${esc(p.system_instructions)}</td>
            <td style="white-space:nowrap;">
              <button class="lip-ao-btn-ghost" data-edit-id="${p.id}">Edit</button>
              <button class="lip-ao-btn-danger" data-del-id="${p.id}">Delete</button>
            </td>
          </tr>`).join("")
        : `<tr><td colspan="4" style="color:#645c7a;">No personas found.</td></tr>`;
    }

    document.getElementById("lip-rbac-count").textContent = `Page ${data.page} of ${data.total_pages} (${data.total} total)`;
    document.getElementById("lip-rbac-prev").disabled = data.page <= 1;
    document.getElementById("lip-rbac-next").disabled = data.page >= data.total_pages;
  }

  async function openModal(item) {
    STATE.editingId = item ? item.id : null;
    const fields = document.getElementById("lip-rbac-modal-fields");
    const title = document.getElementById("lip-rbac-modal-title");

    if (STATE.tab === "users") {
      title.textContent = item ? "Edit User" : "New User";
      fields.innerHTML = `
        <div class="lip-ao-field"><label>Name</label><input id="rbac-f-name" class="lip-ao-input" value="${esc(item?.name || "")}" /></div>
        <div class="lip-ao-field"><label>Email</label><input id="rbac-f-email" class="lip-ao-input" value="${esc(item?.email || "")}" /></div>
        <div class="lip-ao-field"><label>Role</label>
          <select id="rbac-f-role" class="lip-ao-input">
            <option value="admin" ${item?.role === "admin" ? "selected" : ""}>admin</option>
            <option value="editor" ${item?.role === "editor" ? "selected" : ""}>editor</option>
            <option value="viewer" ${!item || item?.role === "viewer" ? "selected" : ""}>viewer</option>
          </select>
        </div>
        <div class="lip-ao-field"><label>Status</label>
          <select id="rbac-f-status" class="lip-ao-input">
            <option value="active" ${!item || item?.status === "active" ? "selected" : ""}>active</option>
            <option value="inactive" ${item?.status === "inactive" ? "selected" : ""}>inactive</option>
          </select>
        </div>`;
    } else if (STATE.tab === "agents") {
      await refreshPersonasCache();
      title.textContent = item ? "Edit Agent" : "New Agent";
      const opts = [`<option value="">-- None --</option>`]
        .concat(STATE.personasCache.map((p) => `<option value="${p.id}" ${item?.persona_id === p.id ? "selected" : ""}>${esc(p.name)}</option>`))
        .join("");
      fields.innerHTML = `
        <div class="lip-ao-field"><label>Agent Name</label><input id="rbac-f-name" class="lip-ao-input" value="${esc(item?.name || "")}" /></div>
        <div class="lip-ao-field"><label>Model</label><input id="rbac-f-model" class="lip-ao-input" value="${esc(item?.model || "gemma4:26b")}" /></div>
        <div class="lip-ao-field"><label>Assigned Persona</label><select id="rbac-f-persona" class="lip-ao-input">${opts}</select></div>
        <div class="lip-ao-field"><label>Status</label>
          <select id="rbac-f-status" class="lip-ao-input">
            <option value="active" ${!item || item?.status === "active" ? "selected" : ""}>active</option>
            <option value="inactive" ${item?.status === "inactive" ? "selected" : ""}>inactive</option>
          </select>
        </div>`;
    } else {
      title.textContent = item ? "Edit Persona" : "New Persona";
      fields.innerHTML = `
        <div class="lip-ao-field"><label>Persona Name</label><input id="rbac-f-name" class="lip-ao-input" value="${esc(item?.name || "")}" /></div>
        <div class="lip-ao-field"><label>Tone</label><input id="rbac-f-tone" class="lip-ao-input" value="${esc(item?.tone || "Warm, plain-English")}" /></div>
        <div class="lip-ao-field"><label>System Instructions</label><textarea id="rbac-f-inst" class="lip-ao-input" rows="4">${esc(item?.system_instructions || "")}</textarea></div>`;
    }

    document.getElementById("lip-rbac-modal-bg").classList.add("open");
  }

  function bindEvents() {
    document.getElementById("lip-rbac-tabs").onclick = (e) => {
      const t = e.target.dataset.tab;
      if (!t) return;
      STATE.tab = t;
      STATE.page = 1;
      document.querySelectorAll("#lip-rbac-tabs .lip-omni-tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === t));
      loadRbac();
    };

    document.getElementById("lip-rbac-search").oninput = (e) => { STATE.q = e.target.value; STATE.page = 1; loadRbac(); };
    document.getElementById("lip-rbac-prev").onclick = () => { if (STATE.page > 1) { STATE.page--; loadRbac(); } };
    document.getElementById("lip-rbac-next").onclick = () => { STATE.page++; loadRbac(); };
    document.getElementById("lip-rbac-add").onclick = () => openModal(null);
    document.getElementById("lip-rbac-cancel").onclick = () => document.getElementById("lip-rbac-modal-bg").classList.remove("open");

    document.getElementById("lip-rbac-save").onclick = async () => {
      let payload = {};
      if (STATE.tab === "users") {
        payload = {
          name: document.getElementById("rbac-f-name").value.trim(),
          email: document.getElementById("rbac-f-email").value.trim(),
          role: document.getElementById("rbac-f-role").value,
          status: document.getElementById("rbac-f-status").value,
        };
      } else if (STATE.tab === "agents") {
        const pid = document.getElementById("rbac-f-persona").value;
        payload = {
          name: document.getElementById("rbac-f-name").value.trim(),
          model: document.getElementById("rbac-f-model").value.trim() || "gemma4:26b",
          persona_id: pid ? Number(pid) : null,
          status: document.getElementById("rbac-f-status").value,
        };
      } else {
        payload = {
          name: document.getElementById("rbac-f-name").value.trim(),
          tone: document.getElementById("rbac-f-tone").value.trim(),
          system_instructions: document.getElementById("rbac-f-inst").value.trim(),
        };
      }
      const url = STATE.editingId ? `/api/admin/${STATE.tab}/${STATE.editingId}` : `/api/admin/${STATE.tab}`;
      const method = STATE.editingId ? "PUT" : "POST";
      const res = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        return alert(err.detail || "Save failed");
      }
      document.getElementById("lip-rbac-modal-bg").classList.remove("open");
      loadRbac();
    };

    document.getElementById("lip-rbac-tbody").onclick = async (e) => {
      const editId = e.target.dataset.editId;
      const delId = e.target.dataset.delId;
      if (editId) {
        const item = STATE.items.find((x) => String(x.id) === editId);
        if (item) openModal(item);
      } else if (delId && confirm("Delete this record?")) {
        await fetch(`/api/admin/${STATE.tab}/${delId}`, { method: "DELETE" });
        loadRbac();
      }
    };
  }

  function hookSwitchView() {
    const orig = window.switchView;
    if (typeof orig !== "function") return;
    window.switchView = function (view) {
      orig(view);
      if (view === "rbac") loadRbac();
    };
  }

  function init() {
    mountRbac();
    hookSwitchView();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();