(function () {
  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function injectStyles() {
    if (document.getElementById("lip-dash-styles")) return;
    const style = document.createElement("style");
    style.id = "lip-dash-styles";
    style.textContent = `
      .lip-dash-section { margin-top:20px; }
      .lip-dash-kpis { display:grid; grid-template-columns:repeat(3, 1fr); gap:14px; margin-bottom:16px; }
      @media (max-width: 900px) { .lip-dash-kpis { grid-template-columns:1fr; } }
      .lip-dash-kpi { background:#fff; border:1px solid #e6e1f2; border-radius:14px; padding:16px 18px; }
      .lip-dash-kpi-label { font-size:11.5px; font-weight:700; text-transform:uppercase; letter-spacing:.04em; color:#645c7a; }
      .lip-dash-kpi-val { font-size:26px; font-weight:700; color:#1f1635; margin:6px 0 4px; line-height:1.1; }
      .lip-dash-kpi-sub { font-size:12.5px; color:#645c7a; }
      .lip-dash-grid { display:grid; grid-template-columns:1fr 1.35fr; gap:16px; align-items:start; }
      @media (max-width: 960px) { .lip-dash-grid { grid-template-columns:1fr; } }
      .lip-dash-bar-row { margin-bottom:12px; }
      .lip-dash-bar-head { display:flex; justify-content:space-between; font-size:13px; color:#1f1635; margin-bottom:5px; }
      .lip-dash-bar-track { height:8px; background:#f3effa; border-radius:999px; overflow:hidden; }
      .lip-dash-bar-fill { height:100%; background:#6d28d9; border-radius:999px; transition:width .25s ease; }
      .lip-dash-actions { display:flex; flex-wrap:wrap; gap:8px; margin-top:14px; padding-top:14px; border-top:1px solid #ece8f5; }
      .lip-dash-pill { display:inline-block; padding:3px 9px; border-radius:999px; font-size:11.5px; font-weight:600; background:#f5f2fc; color:#4c1d95; }
      .lip-dash-pill.unfiled { background:#f1f5f9; color:#64748b; }
    `;
    document.head.appendChild(style);
  }

  function mountIntoOverview() {
    const overview = document.getElementById("view-overview");
    if (!overview || document.getElementById("lip-dash-section")) return;

    injectStyles();

    const sec = document.createElement("div");
    sec.id = "lip-dash-section";
    sec.className = "lip-dash-section";
    sec.innerHTML = `
      <div id="lip-dash-kpis" class="lip-dash-kpis">
        <div class="lip-dash-kpi"><div class="lip-dash-kpi-label">Loading governance metrics...</div></div>
      </div>

      <div class="lip-dash-grid">
        <div class="lip-ao-card" style="padding:18px;">
          <div style="font-size:14.5px;font-weight:700;color:#1f1635;margin-bottom:14px;">Knowledge Base Folders</div>
          <div id="lip-dash-folders">Loading...</div>
          <div class="lip-dash-actions">
            <button type="button" class="lip-ao-btn" data-jump="omnichannel">Open Omnichannel Test</button>
            <button type="button" class="lip-ao-btn-ghost" data-jump="kb">Manage Folders</button>
            <button type="button" class="lip-ao-btn-ghost" data-jump="guardrails">Guardrails</button>
            <button type="button" class="lip-ao-btn-ghost" data-jump="rbac">Roles &amp; Agents</button>
          </div>
        </div>

        <div class="lip-ao-card">
          <div style="padding:14px 16px;border-bottom:1px solid #ece8f5;font-size:14.5px;font-weight:700;color:#1f1635;">
            Recently Ingested Documents
          </div>
          <table class="lip-ao-table">
            <thead>
              <tr>
                <th>Document</th>
                <th style="width:75px;">Pages</th>
                <th style="width:150px;">Folder</th>
              </tr>
            </thead>
            <tbody id="lip-dash-recent">
              <tr><td colspan="3">Loading...</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    `;
    overview.appendChild(sec);

    sec.querySelectorAll("[data-jump]").forEach((b) => {
      b.onclick = () => window.switchView(b.dataset.jump);
    });
  }

  async function loadAnalytics() {
    try {
      const res = await fetch("/api/admin/analytics");
      const d = await res.json();
      const k = d.knowledge || {};
      const gov = d.governance || {};

      document.getElementById("lip-dash-kpis").innerHTML = `
        <div class="lip-dash-kpi">
          <div class="lip-dash-kpi-label">Active Guardrails</div>
          <div class="lip-dash-kpi-val">${gov.guardrails_active ?? 0} <span style="font-size:14px;font-weight:600;color:#645c7a;">/ ${gov.guardrails_total ?? 0}</span></div>
          <div class="lip-dash-kpi-sub">Enforced live on /api/chat</div>
        </div>
        <div class="lip-dash-kpi">
          <div class="lip-dash-kpi-label">Agents &amp; Personas</div>
          <div class="lip-dash-kpi-val">${gov.agents_active ?? 0} <span style="font-size:14px;font-weight:600;color:#645c7a;">Active</span></div>
          <div class="lip-dash-kpi-sub">${gov.personas ?? 0} personas · ${gov.users ?? 0} users</div>
        </div>
        <div class="lip-dash-kpi">
          <div class="lip-dash-kpi-label">KB Organization</div>
          <div class="lip-dash-kpi-val">${k.filed_documents ?? 0} <span style="font-size:14px;font-weight:600;color:#645c7a;">/ ${k.documents ?? 0} filed</span></div>
          <div class="lip-dash-kpi-sub">${(k.total_pages ?? 0).toLocaleString()} pages across ${k.folders ?? 0} folders</div>
        </div>
      `;

      const totalDocs = Math.max(1, k.documents || 0);
      const bars = [
        ...(d.folder_breakdown || []).map((f) => ({ name: f.name, count: f.count, muted: false })),
        { name: "Unfiled", count: k.unfiled_documents ?? 0, muted: true },
      ];
      document.getElementById("lip-dash-folders").innerHTML = bars
        .map((b) => {
          const pct = Math.round((b.count / totalDocs) * 100);
          return `
            <div class="lip-dash-bar-row">
              <div class="lip-dash-bar-head">
                <span style="font-weight:${b.muted ? 500 : 600};color:${b.muted ? "#645c7a" : "#1f1635"};">${esc(b.name)}</span>
                <span style="color:#645c7a;">${b.count} (${pct}%)</span>
              </div>
              <div class="lip-dash-bar-track">
                <div class="lip-dash-bar-fill" style="width:${pct}%;${b.muted ? "background:#cbd5e1;" : ""}"></div>
              </div>
            </div>`;
        })
        .join("");

      const recent = d.recent_documents || [];
      document.getElementById("lip-dash-recent").innerHTML = recent.length
        ? recent
            .map(
              (doc) => `
              <tr>
                <td style="font-weight:600;color:#1f1635;">${esc(doc.name)}</td>
                <td style="color:#645c7a;">${doc.pages}</td>
                <td><span class="lip-dash-pill ${doc.folder === "Unfiled" ? "unfiled" : ""}">${esc(doc.folder)}</span></td>
              </tr>`
            )
            .join("")
        : `<tr><td colspan="3" style="color:#645c7a;text-align:center;padding:20px;">No documents ingested yet.</td></tr>`;
    } catch {}
  }

  function hookSwitchView() {
    const orig = window.switchView;
    if (typeof orig !== "function") return;
    window.switchView = function (view) {
      orig(view);
      if (view === "overview") loadAnalytics();
    };
  }

  function init() {
    mountIntoOverview();
    hookSwitchView();
    loadAnalytics();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();