(function () {
  const STATE = {
    grPage: 1,
    grPageSize: 5,
    grQuery: "",
    grItems: [],
    editingId: null,
    channel: "whatsapp",
    agentId: "",
    histories: { mobile: [], whatsapp: [], email: [], sms: [] },
    lastMeta: null,
  };

  function injectStyles() {
    if (document.getElementById("lip-admin-omni-css")) return;
    const style = document.createElement("style");
    style.id = "lip-admin-omni-css";
    style.textContent = `
      .lip-ao-header { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; margin-bottom:16px; }
      .lip-ao-title { font-size:20px; font-weight:700; color:#1f1635; margin:0; }
      .lip-ao-sub { font-size:13px; color:#645c7a; margin:2px 0 0; }
      .lip-ao-card { background:#fff; border:1px solid #e6e1f2; border-radius:12px; padding:18px; box-shadow:0 1px 3px rgba(31,22,53,.04); }
      .lip-ao-btn { background:#6d28d9; color:#fff; border:none; border-radius:8px; padding:8px 14px; font-weight:600; font-size:13px; cursor:pointer; }
      .lip-ao-btn:hover { background:#5b21b6; }
      .lip-ao-btn-ghost { background:#f5f2fc; color:#4c1d95; border:1px solid #dfd7f5; border-radius:8px; padding:7px 12px; font-weight:600; font-size:12.5px; cursor:pointer; }
      .lip-ao-btn-danger { background:#fef2f2; color:#b91c1c; border:1px solid #fecaca; border-radius:8px; padding:6px 10px; font-weight:600; font-size:12px; cursor:pointer; }
      .lip-ao-input { border:1px solid #d9d2eb; border-radius:8px; padding:8px 12px; font-size:13.5px; font-family:inherit; width:100%; box-sizing:border-box; }
      .lip-ao-badge { display:inline-block; padding:2px 8px; border-radius:999px; font-size:11.5px; font-weight:600; text-transform:uppercase; background:#ede9fe; color:#5b21b6; }
      .lip-ao-table { width:100%; border-collapse:collapse; font-size:13.5px; }
      .lip-ao-table th { text-align:left; padding:10px 12px; border-bottom:2px solid #ede9fe; color:#5b5270; font-size:12px; text-transform:uppercase; }
      .lip-ao-table td { padding:12px; border-bottom:1px solid #f2effa; vertical-align:top; }
      .lip-ao-pager { display:flex; justify-content:space-between; align-items:center; margin-top:14px; font-size:13px; color:#5b5270; }
      .lip-ao-modal-bg { position:fixed; inset:0; background:rgba(20,12,40,.45); display:none; align-items:center; justify-content:center; z-index:9999; }
      .lip-ao-modal-bg.open { display:flex; }
      .lip-ao-modal { background:#fff; border-radius:14px; padding:22px; width:min(480px,92vw); box-shadow:0 16px 40px rgba(0,0,0,.2); }
      .lip-ao-field { margin-bottom:12px; }
      .lip-ao-field label { display:block; font-size:12.5px; font-weight:600; color:#3d3554; margin-bottom:4px; }
      .lip-omni-grid { display:grid; grid-template-columns:1.6fr 1fr; gap:18px; align-items:start; }
      @media (max-width:900px) { .lip-omni-grid { grid-template-columns:1fr; } }
      .lip-omni-tabs { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; }
      .lip-omni-tab { border:1px solid #dfd7f5; background:#fff; color:#4c1d95; padding:7px 14px; border-radius:999px; font-size:13px; font-weight:600; cursor:pointer; }
      .lip-omni-tab.active { background:#6d28d9; color:#fff; border-color:#6d28d9; }
      .lip-omni-frame { border:1px solid #dcd5ee; border-radius:14px; overflow:hidden; background:#faf9fd; display:flex; flex-direction:column; height:500px; }
      .lip-omni-bar { padding:12px 16px; font-weight:700; font-size:13.5px; color:#fff; display:flex; justify-content:space-between; align-items:center; }
      .lip-omni-bar.whatsapp { background:#075e54; }
      .lip-omni-bar.mobile { background:#6d28d9; }
      .lip-omni-bar.email { background:#334155; }
      .lip-omni-bar.sms { background:#1d4ed8; }
      .lip-omni-msgs { flex:1; overflow-y:auto; padding:16px; display:flex; flex-direction:column; gap:10px; }
      .lip-omni-bubble { max-width:82%; padding:10px 13px; border-radius:12px; font-size:13.5px; line-height:1.45; white-space:pre-wrap; }
      .lip-omni-bubble.user { align-self:flex-end; background:#6d28d9; color:#fff; border-bottom-right-radius:3px; }
      .lip-omni-bubble.bot { align-self:flex-start; background:#fff; color:#1f1635; border:1px solid #e6e1f2; border-bottom-left-radius:3px; }
      .lip-omni-input-row { display:flex; gap:8px; padding:12px; background:#fff; border-top:1px solid #e6e1f2; }
      .lip-gr-pill { display:flex; align-items:center; gap:6px; padding:7px 10px; border-radius:8px; background:#f5f2fc; border:1px solid #e6e1f2; font-size:12.5px; margin-bottom:6px; color:#3b1c7a; }
      .lip-agent-picker { position:relative; display:inline-block; }
      .lip-agent-trigger { display:inline-flex; align-items:center; gap:8px; background:#fff; border:1px solid #dfd7f5; border-radius:999px; padding:7px 14px; font-size:13px; font-weight:600; color:#1f1635; cursor:pointer; transition:border-color .15s, box-shadow .15s; font-family:inherit; }
      .lip-agent-trigger:hover, .lip-agent-picker.open .lip-agent-trigger { border-color:#6d28d9; box-shadow:0 0 0 3px rgba(109,40,217,.1); }
      .lip-agent-dot { width:8px; height:8px; border-radius:50%; background:#6d28d9; flex-shrink:0; }
      .lip-agent-tag { font-size:11.5px; font-weight:500; color:#645c7a; background:#f5f2fc; padding:2px 8px; border-radius:999px; }
      .lip-agent-menu { position:absolute; right:0; top:calc(100% + 6px); min-width:270px; background:#fff; border:1px solid #e6e1f2; border-radius:12px; box-shadow:0 12px 28px rgba(31,22,53,.14); padding:6px; display:none; z-index:200; }
      .lip-agent-picker.open .lip-agent-menu { display:block; }
      .lip-agent-opt { display:flex; justify-content:space-between; align-items:center; width:100%; text-align:left; background:transparent; border:none; border-radius:8px; padding:9px 11px; cursor:pointer; font-family:inherit; }
      .lip-agent-opt:hover { background:#f5f2fc; }
      .lip-agent-opt.active { background:#ede9fe; }
      .lip-agent-opt-name { font-size:13px; font-weight:600; color:#1f1635; display:block; }
      .lip-agent-opt-sub { font-size:11.5px; color:#645c7a; display:block; margin-top:1px; }
      .lip-agent-check { color:#6d28d9; font-weight:700; font-size:13px; }
    `;
    document.head.appendChild(style);
  }

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function mountViews() {
    const navList = document.querySelector(".nav-list");
    const firstPanel = document.querySelector(".view-panel");
    if (!navList || !firstPanel || document.getElementById("view-guardrails")) return;

    const btnGr = document.createElement("button");
    btnGr.className = "nav-item";
    btnGr.dataset.view = "guardrails";
    btnGr.textContent = "Guardrails";
    btnGr.onclick = () => window.switchView("guardrails");

    const btnOmni = document.createElement("button");
    btnOmni.className = "nav-item";
    btnOmni.dataset.view = "omnichannel";
    btnOmni.textContent = "Omnichannel Test";
    btnOmni.onclick = () => window.switchView("omnichannel");

    navList.appendChild(btnGr);
    navList.appendChild(btnOmni);

    const container = firstPanel.parentElement;

    const grPanel = document.createElement("section");
    grPanel.id = "view-guardrails";
    grPanel.className = "view-panel";
    grPanel.innerHTML = `
      <div class="lip-ao-header">
        <div>
          <h2 class="lip-ao-title">Guardrail Management</h2>
          <p class="lip-ao-sub">Active rules are injected live into Gemma 4 on every chat and omnichannel test.</p>
        </div>
        <div style="display:flex;gap:8px;align-items:center;">
          <input id="lip-gr-search" class="lip-ao-input" style="width:220px;" placeholder="Search guardrails..." />
          <button id="lip-gr-add" class="lip-ao-btn">+ New Guardrail</button>
        </div>
      </div>
      <div class="lip-ao-card">
        <table class="lip-ao-table">
          <thead><tr><th>Name</th><th>Type</th><th>Rule Instruction</th><th>Active</th><th>Actions</th></tr></thead>
          <tbody id="lip-gr-tbody"><tr><td colspan="5">Loading...</td></tr></tbody>
        </table>
        <div class="lip-ao-pager">
          <span id="lip-gr-count"></span>
          <div style="display:flex;gap:8px;">
            <button id="lip-gr-prev" class="lip-ao-btn-ghost">Prev</button>
            <button id="lip-gr-next" class="lip-ao-btn-ghost">Next</button>
          </div>
        </div>
      </div>
      <div id="lip-gr-modal-bg" class="lip-ao-modal-bg">
        <div class="lip-ao-modal">
          <h3 id="lip-gr-modal-title" style="margin:0 0 14px;color:#1f1635;">New Guardrail</h3>
          <div class="lip-ao-field"><label>Name</label><input id="lip-gr-name" class="lip-ao-input" placeholder="e.g., No Clinical Diagnosis" /></div>
          <div class="lip-ao-field"><label>Rule Type</label>
            <select id="lip-gr-type" class="lip-ao-input">
              <option value="safety">safety</option><option value="tone">tone</option>
              <option value="grounding">grounding</option><option value="policy">policy</option>
            </select>
          </div>
          <div class="lip-ao-field"><label>Rule Instruction</label><textarea id="lip-gr-text" class="lip-ao-input" rows="4" placeholder="Instruction enforced on Gemma 4..."></textarea></div>
          <div class="lip-ao-field"><label><input type="checkbox" id="lip-gr-enabled" checked /> Enabled</label></div>
          <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:14px;">
            <button id="lip-gr-cancel" class="lip-ao-btn-ghost">Cancel</button>
            <button id="lip-gr-save" class="lip-ao-btn">Save Guardrail</button>
          </div>
        </div>
      </div>
    `;

    const omniPanel = document.createElement("section");
    omniPanel.id = "view-omnichannel";
    omniPanel.className = "view-panel";
    omniPanel.innerHTML = `
      <div class="lip-ao-header">
        <div>
          <h2 class="lip-ao-title">Omnichannel Mock Interface</h2>
          <p class="lip-ao-sub">Prototype testbench — preview how LIP adapts tone, length, and guardrails across channels.</p>
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
          <div id="lip-agent-picker" class="lip-agent-picker">
            <button type="button" id="lip-agent-trigger" class="lip-agent-trigger">
              <span class="lip-agent-dot"></span>
              <span id="lip-agent-label">Default LIP Advisor</span>
              <span id="lip-agent-tag" class="lip-agent-tag">Standard</span>
            </button>
            <div id="lip-agent-menu" class="lip-agent-menu"></div>
          </div>
          <button id="lip-omni-clear" class="lip-ao-btn-ghost">Clear Channel</button>
        </div>
      </div>
      <div class="lip-omni-tabs" id="lip-omni-tabs">
        <button class="lip-omni-tab active" data-ch="whatsapp">WhatsApp</button>
        <button class="lip-omni-tab" data-ch="mobile">Mobile App</button>
        <button class="lip-omni-tab" data-ch="email">Email</button>
        <button class="lip-omni-tab" data-ch="sms">SMS</button>
      </div>
      <div class="lip-omni-grid">
        <div class="lip-omni-frame">
          <div id="lip-omni-bar" class="lip-omni-bar whatsapp">
            <span id="lip-omni-bar-title">WhatsApp Business Mock — LIP Advisor</span>
            <span style="font-size:11.5px;opacity:.85;">gemma4:26b</span>
          </div>
          <div id="lip-omni-msgs" class="lip-omni-msgs"></div>
          <div class="lip-omni-input-row">
            <input id="lip-omni-input" class="lip-ao-input" placeholder="Type a test message..." />
            <button id="lip-omni-send" class="lip-ao-btn">Send</button>
          </div>
        </div>
        <div class="lip-ao-card">
          <h3 style="margin:0 0 10px;font-size:15px;color:#1f1635;">Live Governance & Context</h3>
          <div id="lip-omni-meta" style="font-size:12.5px;color:#5b5270;margin-bottom:12px;">Send a message to inspect applied guardrails and channel formatting.</div>
          <div style="font-size:12px;font-weight:700;text-transform:uppercase;color:#645c7a;margin-bottom:8px;">Active Guardrails</div>
          <div id="lip-omni-guardrails">Loading...</div>
        </div>
      </div>
    `;

    container.appendChild(grPanel);
    container.appendChild(omniPanel);

    bindEvents();
  }

  async function loadGuardrails() {
    const q = encodeURIComponent(STATE.grQuery);
    const res = await fetch(`/api/admin/guardrails?page=${STATE.grPage}&page_size=${STATE.grPageSize}&q=${q}`);
    const data = await res.json();
    STATE.grItems = data.items || [];
    const tbody = document.getElementById("lip-gr-tbody");
    if (!tbody) return;
    if (!STATE.grItems.length) {
      tbody.innerHTML = `<tr><td colspan="5" style="color:#645c7a;">No guardrails found.</td></tr>`;
    } else {
      tbody.innerHTML = STATE.grItems.map((g) => `
        <tr>
          <td><strong>${esc(g.name)}</strong></td>
          <td><span class="lip-ao-badge">${esc(g.rule_type)}</span></td>
          <td>${esc(g.rule_text)}</td>
          <td><input type="checkbox" ${g.enabled ? "checked" : ""} data-toggle-id="${g.id}" /></td>
          <td style="white-space:nowrap;">
            <button class="lip-ao-btn-ghost" data-edit-id="${g.id}">Edit</button>
            <button class="lip-ao-btn-danger" data-del-id="${g.id}">Delete</button>
          </td>
        </tr>
      `).join("");
    }
    document.getElementById("lip-gr-count").textContent = `Page ${data.page} of ${data.total_pages} (${data.total} total)`;
    document.getElementById("lip-gr-prev").disabled = data.page <= 1;
    document.getElementById("lip-gr-next").disabled = data.page >= data.total_pages;
  }

  async function loadOmniGuardrails() {
    const box = document.getElementById("lip-omni-guardrails");
    if (!box) return;
    const res = await fetch("/api/admin/guardrails?page=1&page_size=50");
    const data = await res.json();
    const active = (data.items || []).filter((g) => g.enabled);
    box.innerHTML = active.length
      ? active.map((g) => `<div class="lip-gr-pill"><strong>[${esc(g.rule_type)}]</strong> ${esc(g.name)}</div>`).join("")
      : `<div style="font-size:12.5px;color:#645c7a;">No active guardrails enabled.</div>`;
  }

  async function loadOmniAgents() {
    const menu = document.getElementById("lip-agent-menu");
    if (!menu) return;
    try {
      const res = await fetch("/api/admin/agents?page=1&page_size=50");
      const data = await res.json();
      const active = (data.items || []).filter((a) => a.status === "active");
      STATE.agentsList = [
        { id: "", name: "Default LIP Advisor", persona_name: "Standard" },
        ...active.map((a) => ({ id: String(a.id), name: a.name, persona_name: a.persona_name || "Standard" })),
      ];
      renderAgentPicker();
    } catch {}
  }

  function renderAgentPicker() {
    const menu = document.getElementById("lip-agent-menu");
    const label = document.getElementById("lip-agent-label");
    const tag = document.getElementById("lip-agent-tag");
    if (!menu || !label || !tag) return;
    const list = STATE.agentsList || [{ id: "", name: "Default LIP Advisor", persona_name: "Standard" }];
    const current = list.find((a) => a.id === String(STATE.agentId || "")) || list[0];
    label.textContent = current.name;
    tag.textContent = current.persona_name;
    menu.innerHTML = list.map((a) => {
      const isAct = a.id === current.id;
      return `<button type="button" class="lip-agent-opt ${isAct ? "active" : ""}" data-agent-id="${esc(a.id)}">
        <span><span class="lip-agent-opt-name">${esc(a.name)}</span><span class="lip-agent-opt-sub">${esc(a.persona_name)}</span></span>
        ${isAct ? '<span class="lip-agent-check">&#10003;</span>' : ""}
      </button>`;
    }).join("");
  }

  function renderOmniMessages() {
    const titles = {
      whatsapp: "WhatsApp Business Mock — LIP Advisor",
      mobile: "Mobile App Mock — LIP Advisor",
      email: "Email Client Mock — LIP Advisor",
      sms: "SMS Messaging Mock — LIP Advisor",
    };
    const bar = document.getElementById("lip-omni-bar");
    bar.className = `lip-omni-bar ${STATE.channel}`;
    document.getElementById("lip-omni-bar-title").textContent = titles[STATE.channel];
    const msgs = STATE.histories[STATE.channel] || [];
    const el = document.getElementById("lip-omni-msgs");
    el.innerHTML = msgs.length
      ? msgs.map((m) => `<div class="lip-omni-bubble ${m.role}">${esc(m.text)}</div>`).join("")
      : `<div style="color:#7c7491;font-size:13px;text-align:center;margin-top:40px;">Start a ${STATE.channel.toUpperCase()} test conversation below.</div>`;
    el.scrollTop = el.scrollHeight;
  }

  async function sendOmniMessage() {
    const input = document.getElementById("lip-omni-input");
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    const ch = STATE.channel;
    STATE.histories[ch].push({ role: "user", text });
    STATE.histories[ch].push({ role: "bot", text: "Thinking..." });
    renderOmniMessages();
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, channel: ch, agent_id: STATE.agentId ? Number(STATE.agentId) : null }),
      });
      const data = await res.json();
      STATE.histories[ch][STATE.histories[ch].length - 1] = {
        role: "bot",
        text: data.reply || data.detail || "No reply returned.",
      };
      document.getElementById("lip-omni-meta").innerHTML =
        `<strong>Agent:</strong> ${esc(data.agent_name || "Default LIP Advisor")} (${esc(data.persona_name || "Standard")})<br>` +
        `<strong>Channel:</strong> ${esc(data.channel || ch)} &nbsp;|&nbsp; <strong>Semantic hits:</strong> ${data.semantic_hits ?? 0}<br>` +
        `<strong>Applied Guardrails:</strong> ${(data.applied_guardrails || []).map(esc).join(", ") || "None"}`;
    } catch (e) {
      STATE.histories[ch][STATE.histories[ch].length - 1] = { role: "bot", text: "Error: " + e.message };
    }
    renderOmniMessages();
  }

  function openModal(item) {
    STATE.editingId = item ? item.id : null;
    document.getElementById("lip-gr-modal-title").textContent = item ? "Edit Guardrail" : "New Guardrail";
    document.getElementById("lip-gr-name").value = item ? item.name : "";
    document.getElementById("lip-gr-type").value = item ? item.rule_type : "policy";
    document.getElementById("lip-gr-text").value = item ? item.rule_text : "";
    document.getElementById("lip-gr-enabled").checked = item ? !!item.enabled : true;
    document.getElementById("lip-gr-modal-bg").classList.add("open");
  }

  function bindEvents() {
    document.getElementById("lip-gr-add").onclick = () => openModal(null);
    document.getElementById("lip-gr-cancel").onclick = () => document.getElementById("lip-gr-modal-bg").classList.remove("open");
    document.getElementById("lip-gr-prev").onclick = () => { if (STATE.grPage > 1) { STATE.grPage--; loadGuardrails(); } };
    document.getElementById("lip-gr-next").onclick = () => { STATE.grPage++; loadGuardrails(); };
    document.getElementById("lip-gr-search").oninput = (e) => { STATE.grQuery = e.target.value; STATE.grPage = 1; loadGuardrails(); };

    document.getElementById("lip-gr-save").onclick = async () => {
      const payload = {
        name: document.getElementById("lip-gr-name").value.trim(),
        rule_type: document.getElementById("lip-gr-type").value,
        rule_text: document.getElementById("lip-gr-text").value.trim(),
        enabled: document.getElementById("lip-gr-enabled").checked,
      };
      if (!payload.name || !payload.rule_text) return alert("Name and Rule Instruction are required.");
      const url = STATE.editingId ? `/api/admin/guardrails/${STATE.editingId}` : "/api/admin/guardrails";
      const method = STATE.editingId ? "PUT" : "POST";
      await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      document.getElementById("lip-gr-modal-bg").classList.remove("open");
      loadGuardrails();
    };

    document.getElementById("lip-gr-tbody").onclick = async (e) => {
      const editId = e.target.dataset.editId;
      const delId = e.target.dataset.delId;
      const toggleId = e.target.dataset.toggleId;
      if (editId) {
        const item = STATE.grItems.find((g) => String(g.id) === editId);
        if (item) openModal(item);
      } else if (delId && confirm("Delete this guardrail?")) {
        await fetch(`/api/admin/guardrails/${delId}`, { method: "DELETE" });
        loadGuardrails();
      } else if (toggleId) {
        const item = STATE.grItems.find((g) => String(g.id) === toggleId);
        if (item) {
          await fetch(`/api/admin/guardrails/${toggleId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ...item, enabled: e.target.checked }),
          });
          loadGuardrails();
        }
      }
    };

    document.getElementById("lip-omni-tabs").onclick = (e) => {
      const ch = e.target.dataset.ch;
      if (!ch) return;
      STATE.channel = ch;
      document.querySelectorAll(".lip-omni-tab").forEach((b) => b.classList.toggle("active", b.dataset.ch === ch));
      renderOmniMessages();
    };
    document.getElementById("lip-omni-send").onclick = sendOmniMessage;
    document.getElementById("lip-omni-input").onkeydown = (e) => { if (e.key === "Enter") sendOmniMessage(); };
    document.getElementById("lip-omni-clear").onclick = () => { STATE.histories[STATE.channel] = []; renderOmniMessages(); };
    const picker = document.getElementById("lip-agent-picker");
    document.getElementById("lip-agent-trigger").onclick = (e) => {
      e.stopPropagation();
      picker.classList.toggle("open");
    };
    document.getElementById("lip-agent-menu").onclick = (e) => {
      const opt = e.target.closest("[data-agent-id]");
      if (!opt) return;
      STATE.agentId = opt.dataset.agentId;
      renderAgentPicker();
      picker.classList.remove("open");
    };
    document.addEventListener("click", (e) => {
      if (picker && !picker.contains(e.target)) picker.classList.remove("open");
    });
  }

  function hookSwitchView() {
    const orig = window.switchView;
    if (typeof orig !== "function") return;
    window.switchView = function (view) {
      orig(view);
      if (view === "guardrails") loadGuardrails();
      if (view === "omnichannel") { loadOmniGuardrails(); loadOmniAgents(); renderOmniMessages(); }
    };
  }

  function init() {
    injectStyles();
    mountViews();
    hookSwitchView();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();