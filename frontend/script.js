const API_BASE = "/api";

let authToken = null;
let currentPapers = [];
let filterOptions = { domains: [] };
let selectedDomains = new Set();
let eDomainEdited = false;
let currentSection = "home";

// ---------------- helpers ----------------
function $(id) { return document.getElementById(id); }

function openModal(id) { $(id).classList.add("open"); }
function closeModal(id) { $(id).classList.remove("open"); }

document.querySelectorAll("[data-close]").forEach(btn => {
  btn.addEventListener("click", () => closeModal(btn.dataset.close));
});
document.querySelectorAll(".modal-backdrop").forEach(bd => {
  bd.addEventListener("click", (e) => { if (e.target === bd) bd.classList.remove("open"); });
});

async function api(path, options = {}) {
  const headers = options.headers || {};
  if (options.body) headers["Content-Type"] = "application/json";
  if (authToken) headers["Authorization"] = "Bearer " + authToken;
  const res = await fetch(API_BASE + path, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Request failed");
  return data;
}

// raw upload (multipart) — does NOT set Content-Type, browser handles the boundary
async function apiUpload(path, formData) {
  const headers = {};
  if (authToken) headers["Authorization"] = "Bearer " + authToken;
  const res = await fetch(API_BASE + path, { method: "POST", headers, body: formData });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Request failed");
  return data;
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str).replace(/[&<>"']/g, m => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
}

// ---------------- profile ----------------
// ============ Profile Blocks System ============
const DEFAULT_BLOCK_ORDER = ["header", "contact", "research_interest", "education", "accolades", "employment", "other_records"];
let profileLayout = {}; // { block_order: [...], hidden_blocks: [...], items: { education: { order: [...], hidden: [...] } } }
let scientistData = null;

async function loadProfile() {
  try {
    scientistData = await api("/scientist");
    const s = scientistData;
    $("scientistCard").querySelector(".scientist-name").textContent = s.name;
    $("scientistCard").querySelector(".scientist-role").textContent =
      `${s.designation} · ${s.institute.split("(")[1]?.replace(")", "") || s.institute}`;

    try { profileLayout = await api("/profile-layout"); } catch { profileLayout = {}; }
    renderProfileBlocks();
  } catch (e) { /* backend not reachable yet */ }
}

function renderProfileBlocks() {
  const s = scientistData;
  if (!s) return;
  const container = $("profileBlocks");
  const isAdmin = !!authToken;
  const blockOrder = profileLayout.block_order || DEFAULT_BLOCK_ORDER;
  const hiddenBlocks = new Set(profileLayout.hidden_blocks || []);
  const items = profileLayout.items || {};

  const blockRenderers = {
    header: () => {
      const inner = `
        <div class="block-header-inner">
          <div class="block-photo-col">
            <img src="yeasin-photo.png" alt="Photo of ${escapeHtml(s.name)}" class="block-photo">
            <div class="block-links">
              <a href="https://scholar.google.com/citations?user=xejMKD0AAAAJ&hl=en&oi=sra" target="_blank" rel="noopener" class="block-link-btn"><i class="fas fa-graduation-cap"></i>
                <span>Google Scholar</span></a>
              <a href="https://www.linkedin.com/in/dr-yeasin/" target="_blank" rel="noopener" class="block-link-btn"><i class="fab fa-linkedin"></i>
                <span>LinkedIn</span></a>
            </div>
          </div>
          <div>
            <h1 class="block-name">${escapeHtml(s.name)}</h1>
            <p class="block-role">${escapeHtml(s.designation)} &middot; ${escapeHtml(s.institute)}</p>
            <p class="block-address">${escapeHtml(s.address || "")}</p>
          </div>
        </div>`;
      return { title: "", html: inner };
    },

    contact: () => {
      const parts = [];
      if (s.dob) parts.push(`<div class="block-contact-item"><span class="block-contact-label">DOB</span><span class="block-contact-value">${escapeHtml(s.dob)}</span></div>`);
      if (s.mobile?.length) parts.push(`<div class="block-contact-item"><span class="block-contact-label">Mobile</span><span class="block-contact-value">${s.mobile.map(escapeHtml).join(" / ")}</span></div>`);
      if (s.email?.length) parts.push(`<div class="block-contact-item"><span class="block-contact-label">Email</span><span class="block-contact-value">${s.email.map(escapeHtml).join(", ")}</span></div>`);
      return { title: "Contact", html: `<div class="block-contact-grid">${parts.join("")}</div>` };
    },

    research_interest: () => ({
      title: "Research Interest",
      html: `<p class="block-interest-text">${escapeHtml(s.research_interest || "")}</p>`
    }),

    education: () => renderListBlock("Education", s.education || [], "education",
      e => `<strong>${escapeHtml(e.degree)}</strong> (${escapeHtml(e.year)}) &middot; ${escapeHtml(e.institution)}`),

    accolades: () => renderListBlock("Academic Accolades", s.accolades || [], "accolades",
      a => escapeHtml(a)),

    employment: () => renderListBlock("Employment", s.employment || [], "employment",
      e => `<strong>${escapeHtml(e.period)}</strong> &middot; ${escapeHtml(e.role)}, ${escapeHtml(e.institution)}`),

    other_records: () => renderListBlock("Other Records", s.other_records || [], "other_records",
      r => escapeHtml(r)),
  };

  function renderListBlock(title, dataItems, key, renderFn) {
    const itemConfig = items[key] || {};
    const order = itemConfig.order || dataItems.map((_, i) => i);
    const hiddenItems = new Set(itemConfig.hidden || []);

    const listHtml = order.map(idx => {
      if (idx >= dataItems.length) return "";
      const hidden = hiddenItems.has(idx);
      if (hidden && !isAdmin) return "";
      return `<li class="block-list-item${hidden ? " item-hidden" : ""}" data-item-idx="${idx}">
        <span class="item-drag-handle" title="Drag to reorder">⠿</span>
        <span class="item-text">${renderFn(dataItems[idx])}</span>
        <button class="item-toggle-btn" data-block="${key}" data-idx="${idx}">${hidden ? "Show" : "Hide"}</button>
      </li>`;
    }).join("");

    return { title, html: `<ul class="block-list" data-block-key="${key}">${listHtml}</ul>` };
  }

  let html = "";
  for (const blockId of blockOrder) {
    const renderer = blockRenderers[blockId];
    if (!renderer) continue;
    const isHidden = hiddenBlocks.has(blockId);
    if (isHidden && !isAdmin) continue;
    const { title, html: content } = renderer();

    html += `<div class="profile-block${isHidden ? " block-hidden" : ""}" data-block-id="${blockId}">
      ${title || isAdmin ? `<div class="profile-block-header">
        <h3 class="profile-block-title">${escapeHtml(title)}</h3>
        <div class="profile-block-admin">
          <span class="block-drag-handle" title="Drag to reorder">⠿</span>
          <button class="block-toggle-btn" data-block="${blockId}">${isHidden ? "Show" : "Hide"}</button>
        </div>
      </div>` : ""}
      ${content}
    </div>`;
  }
  container.innerHTML = html;

  // Add admin-logged-in class for CSS-based admin control visibility
  document.body.classList.toggle("admin-logged-in", isAdmin);

  // Wire up block hide/show buttons
  container.querySelectorAll(".block-toggle-btn").forEach(btn => {
    btn.addEventListener("click", () => toggleBlock(btn.dataset.block));
  });

  // Wire up item hide/show buttons
  container.querySelectorAll(".item-toggle-btn").forEach(btn => {
    btn.addEventListener("click", () => toggleItem(btn.dataset.block, parseInt(btn.dataset.idx)));
  });

  // Initialize drag-and-drop for blocks
  if (isAdmin && typeof Sortable !== "undefined") {
    new Sortable(container, {
      animation: 200,
      handle: ".block-drag-handle",
      ghostClass: "sortable-ghost",
      dragClass: "sortable-drag",
      onEnd: () => saveBlockOrder(),
    });

    // Initialize drag-and-drop for items within list blocks
    container.querySelectorAll(".block-list").forEach(list => {
      new Sortable(list, {
        animation: 150,
        handle: ".item-drag-handle",
        ghostClass: "sortable-ghost",
        onEnd: () => saveItemOrder(list.dataset.blockKey, list),
      });
    });
  }
}

function toggleBlock(blockId) {
  const hidden = new Set(profileLayout.hidden_blocks || []);
  if (hidden.has(blockId)) hidden.delete(blockId); else hidden.add(blockId);
  profileLayout.hidden_blocks = [...hidden];
  saveLayout();
  renderProfileBlocks();
}

function toggleItem(blockKey, idx) {
  if (!profileLayout.items) profileLayout.items = {};
  if (!profileLayout.items[blockKey]) profileLayout.items[blockKey] = {};
  const hidden = new Set(profileLayout.items[blockKey].hidden || []);
  if (hidden.has(idx)) hidden.delete(idx); else hidden.add(idx);
  profileLayout.items[blockKey].hidden = [...hidden];
  saveLayout();
  renderProfileBlocks();
}

function saveBlockOrder() {
  const container = $("profileBlocks");
  const ids = [...container.querySelectorAll(".profile-block")].map(el => el.dataset.blockId);
  profileLayout.block_order = ids;
  saveLayout();
}

function saveItemOrder(blockKey, list) {
  const indices = [...list.querySelectorAll(".block-list-item")].map(el => parseInt(el.dataset.itemIdx));
  if (!profileLayout.items) profileLayout.items = {};
  if (!profileLayout.items[blockKey]) profileLayout.items[blockKey] = {};
  profileLayout.items[blockKey].order = indices;
  saveLayout();
}

let layoutSaveTimer = null;
function saveLayout() {
  clearTimeout(layoutSaveTimer);
  layoutSaveTimer = setTimeout(async () => {
    try {
      await api("/profile-layout", { method: "PUT", body: JSON.stringify(profileLayout) });
    } catch (e) { console.error("Failed to save layout:", e); }
  }, 500);
}

// ---------------- section nav ----------------
document.querySelectorAll(".nav-tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".nav-tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    document.querySelectorAll(".section-panel").forEach(p => p.classList.add("hidden"));
    currentSection = tab.dataset.section;
    $("section-" + currentSection).classList.remove("hidden");
    loadSection(currentSection);
  });
});

function loadSection(section) {
  if (section === "publications") { loadPapers(); return; }
  const map = {
    "awards": { endpoint: "/awards", render: renderAwards, container: "awardsList" },
    "projects": { endpoint: "/projects", render: renderProjects, container: "projectsList" },
    "book-chapters": { endpoint: "/book-chapters", render: renderBookChapters, container: "bookChaptersList" },
    "software": { endpoint: "/software", render: renderSoftware, container: "softwareList" },
  };
  const cfg = map[section];
  if (!cfg) return;
  api(cfg.endpoint).then(items => cfg.render(items)).catch(() => {
    $(cfg.container).innerHTML = `<div class="empty-state">Could not load this section.</div>`;
  });
}

// ---------------- filters (publications) ----------------
async function loadFilterOptions() {
  const opts = await api("/papers/filters");
  filterOptions = opts;
  fillSelect("fJournal", opts.journals);
  fillSelect("fQuartile", opts.quartiles);
  renderDomainOptions(opts.domains);
  if (opts.year_bounds && opts.year_bounds.min != null) {
    $("fYearMin").placeholder = `From (${opts.year_bounds.min})`;
    $("fYearMax").placeholder = `To (${opts.year_bounds.max})`;
  }
}

function fillSelect(id, values) {
  const sel = $(id);
  const current = sel.value;
  sel.innerHTML = sel.querySelector("option").outerHTML;
  values.forEach(v => {
    const o = document.createElement("option");
    o.value = v; o.textContent = v;
    sel.appendChild(o);
  });
  sel.value = current;
}

function renderDomainOptions(domains) {
  const panel = $("domainPanel");
  panel.innerHTML = domains.map(d => `
    <label class="multiselect-option">
      <input type="checkbox" value="${escapeHtml(d)}" ${selectedDomains.has(d) ? "checked" : ""}>
      <span>${escapeHtml(d)}</span>
    </label>
  `).join("");
  panel.querySelectorAll("input[type=checkbox]").forEach(cb => {
    cb.addEventListener("change", () => {
      if (cb.checked) selectedDomains.add(cb.value); else selectedDomains.delete(cb.value);
      updateDomainToggleLabel();
      loadPapers();
    });
  });
}

function updateDomainToggleLabel() {
  const toggle = $("domainToggle");
  if (selectedDomains.size === 0) toggle.textContent = "All domains";
  else if (selectedDomains.size === 1) toggle.textContent = [...selectedDomains][0];
  else toggle.textContent = `${selectedDomains.size} domains selected`;
}

$("domainToggle").addEventListener("click", () => {
  $("domainPanel").classList.toggle("hidden");
});
document.addEventListener("click", (e) => {
  if (!$("domainMultiselect").contains(e.target)) $("domainPanel").classList.add("hidden");
});

function buildQuery() {
  const p = new URLSearchParams();
  if ($("fYearMin").value) p.set("year_min", $("fYearMin").value);
  if ($("fYearMax").value) p.set("year_max", $("fYearMax").value);
  if ($("fJournal").value) p.set("journal", $("fJournal").value);
  if ($("fQuartile").value) p.set("quartile", $("fQuartile").value);
  if ($("fField").value) p.set("field", $("fField").value);
  if (selectedDomains.size) p.set("domains", [...selectedDomains].join(","));
  if ($("fSearch").value.trim()) p.set("q", $("fSearch").value.trim());
  p.set("sort", $("fSort").value);
  return p.toString();
}

async function loadStats() {
  try {
    const s = await api("/papers/stats");
    const years = s.by_year.length;
    const domainCount = (filterOptions.domains && filterOptions.domains.length) || s.by_domain.length;
    $("statRow").innerHTML = `
      <div class="stat-item"><span class="stat-num">${s.total}</span><span class="stat-label">Publications</span></div>
      <div class="stat-item"><span class="stat-num">${years}</span><span class="stat-label">Years covered</span></div>
      <div class="stat-item"><span class="stat-num">${domainCount}</span><span class="stat-label">Research domains</span></div>
    `;
  } catch (e) {
    $("statRow").innerHTML = `<p style="color:var(--brick); font-size:0.85rem;">Backend not reachable. Start the Flask server (see README) at localhost:5000.</p>`;
  }
}

let currentPubSubtab = "all"; // "all" | "selected"

async function loadPapers() {
  const meta = $("resultsMeta");
  meta.textContent = "Loading...";
  try {
    const query = buildQuery();
    const papers = await api("/papers?" + query);
    currentPapers = papers;
    const shown = currentPubSubtab === "selected" ? papers.filter(p => p.selected) : papers;
    renderPapers(shown);
    meta.textContent = `${shown.length} publication${shown.length !== 1 ? "s" : ""} found`;
  } catch (e) {
    $("paperList").innerHTML = `<div class="empty-state">Could not load records. Is the backend running at ${API_BASE}?</div>`;
    meta.textContent = "";
  }
}

document.querySelectorAll(".pub-subtab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".pub-subtab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    currentPubSubtab = tab.dataset.subtab;
    const shown = currentPubSubtab === "selected" ? currentPapers.filter(p => p.selected) : currentPapers;
    renderPapers(shown);
    $("resultsMeta").textContent = `${shown.length} publication${shown.length !== 1 ? "s" : ""} found`;
  });
});

function renderPapers(papers) {
  const list = $("paperList");
  if (!papers.length) {
    const emptyMsg = currentPubSubtab === "selected"
      ? `No papers selected yet. Use the &#9733; star button on a paper in "All" to feature it here.`
      : "No publications match these filters.";
    list.innerHTML = `<div class="empty-state">${emptyMsg}</div>`;
    return;
  }
  list.innerHTML = papers.map((p, i) => {
    const domainTags = (p.domain || "").split(",").map(d => d.trim()).filter(Boolean)
      .map(d => `<span class="tag tag-domain">${escapeHtml(d)}</span>`).join("");
    return `
    <div class="paper-entry" data-id="${p.publication_id}">
      <div class="paper-index">${String(i + 1).padStart(2, "0")}</div>
      <div>
        <h3 class="paper-title">${escapeHtml(p.title)}</h3>
        <div class="paper-meta">${escapeHtml(p.authors)}${p.journal ? " &middot; " + escapeHtml(p.journal) : ""}${p.publisher ? " (" + escapeHtml(p.publisher) + ")" : ""}</div>
        <div class="paper-tags">
          ${domainTags}
          ${p.field ? `<span class="tag tag-domain">${escapeHtml(p.field)}</span>` : ""}
          ${p.quartile ? `<span class="tag tag-quartile-${p.quartile}">${escapeHtml(p.quartile)}</span>` : ""}
          ${p.naas_score ? `<span class="tag tag-naas">NAAS ${escapeHtml(p.naas_score)}</span>` : ""}
          ${p.hidden ? `<span class="tag tag-hidden">Hidden</span>` : ""}
          ${p.selected ? `<span class="tag tag-selected">&#9733; Selected</span>` : ""}
          ${p.issn ? `<span class="paper-doi">ISSN ${escapeHtml(p.issn)}</span>` : ""}
          ${p.doi ? `<span class="paper-doi"><a href="${p.doi.startsWith("http") ? p.doi : "https://doi.org/" + p.doi}" target="_blank" rel="noopener">${escapeHtml(p.doi)}</a></span>` : ""}
        </div>
      </div>
      <div class="paper-side">
        <div class="paper-year">${escapeHtml(p.year || "—")}</div>
        ${p.impact_factor ? `<div class="paper-if">IF ${escapeHtml(p.impact_factor)}</div>` : ""}
        <div class="admin-actions ${authToken ? "visible" : ""}">
          <button class="select-star-btn ${p.selected ? "is-selected" : ""}" data-toggle-selected="${p.publication_id}" title="${p.selected ? "Remove from Selected" : "Add to Selected"}">&#9733;</button>
          <button class="icon-btn" data-edit="${p.publication_id}">Edit</button>
          <button class="icon-btn" data-toggle-hidden="${p.publication_id}">${p.hidden ? "Show" : "Hide"}</button>
          <button class="icon-btn danger" data-delete="${p.publication_id}">Delete</button>
        </div>
      </div>
    </div>
  `; }).join("");

  list.querySelectorAll("[data-edit]").forEach(b => b.addEventListener("click", () => openEditModal(b.dataset.edit)));
  list.querySelectorAll("[data-delete]").forEach(b => b.addEventListener("click", () => deletePaper(b.dataset.delete)));
  list.querySelectorAll("[data-toggle-hidden]").forEach(b => b.addEventListener("click", () => toggleHidden(b.dataset.toggleHidden)));
  list.querySelectorAll("[data-toggle-selected]").forEach(b => b.addEventListener("click", () => toggleSelected(b.dataset.toggleSelected)));
}

async function toggleSelected(id) {
  try {
    await api(`/papers/${id}/toggle-selected`, { method: "POST" });
    await loadPapers();
  } catch (e) {
    alert(e.message);
  }
}

["fJournal", "fQuartile", "fField", "fSort"].forEach(id => {
  $(id).addEventListener("change", loadPapers);
});
let yearFilterTimer;
["fYearMin", "fYearMax"].forEach(id => {
  $(id).addEventListener("input", () => {
    clearTimeout(yearFilterTimer);
    yearFilterTimer = setTimeout(loadPapers, 400);
  });
});
let searchTimer;
$("fSearch").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadPapers, 350);
});
$("clearFilters").addEventListener("click", () => {
  $("fYearMin").value = ""; $("fYearMax").value = "";
  $("fJournal").value = ""; $("fQuartile").value = ""; $("fField").value = "";
  $("fSearch").value = ""; $("fSort").value = "year_desc";
  selectedDomains.clear();
  updateDomainToggleLabel();
  renderDomainOptions(filterOptions.domains || []);
  loadPapers();
});

// ---------------- admin login / OTP ----------------
$("adminBtn").addEventListener("click", () => {
  if (authToken) {
    authToken = null;
    $("adminBtn").textContent = "Admin";
    onAuthChange();
    return;
  }
  $("loginStep1").classList.remove("hidden");
  $("loginStep2").classList.add("hidden");
  $("loginError").textContent = "";
  openModal("loginModalBackdrop");
});

$("loginSubmit").addEventListener("click", async () => {
  $("loginError").textContent = "";
  try {
    const res = await api("/login", {
      method: "POST",
      body: JSON.stringify({ email: $("loginEmail").value, password: $("loginPassword").value }),
    });
    $("loginStep1").classList.add("hidden");
    $("loginStep2").classList.remove("hidden");
    $("devOtpHint").textContent = res.dev_otp
      ? `Dev mode (no SMTP configured): your OTP is ${res.dev_otp}`
      : "";
  } catch (e) {
    $("loginError").textContent = e.message;
  }
});

$("otpSubmit").addEventListener("click", async () => {
  $("otpError").textContent = "";
  try {
    const res = await api("/verify-otp", {
      method: "POST",
      body: JSON.stringify({ email: $("loginEmail").value, otp: $("otpInput").value }),
    });
    authToken = res.token;
    $("adminBtn").textContent = "Sign out";
    closeModal("loginModalBackdrop");
    onAuthChange();
  } catch (e) {
    $("otpError").textContent = e.message;
  }
});

// ---------------- add publication button (now lives in the Publications tab itself) ----------------
$("addPublicationBtn").addEventListener("click", () => {
  $("addError").textContent = ""; $("addSuccess").textContent = "";
  openModal("addModalBackdrop");
});

function onAuthChange() {
  const visible = !!authToken;
  $("addPublicationBtn").classList.toggle("hidden", !visible);
  $("enrichAllBtn").classList.toggle("hidden", !visible);
  $("exportBackupBtn").classList.toggle("hidden", !visible);
  $("exportSnapshotBtn").classList.toggle("hidden", !visible);
  $("resetScoresBtn").classList.toggle("hidden", !visible);
  $("uploadNaasBtn").classList.toggle("hidden", !visible);
  $("uploadJcrBtn").classList.toggle("hidden", !visible);
  $("downloadCvBtn").classList.toggle("hidden", !visible);
  document.querySelectorAll(".add-record-btn").forEach(b => b.classList.toggle("hidden", !visible));
  // re-render profile blocks so admin controls (drag handles, hide buttons) appear/disappear
  renderProfileBlocks();
  // re-render whichever section is active so admin action buttons show/hide
  loadSection(currentSection);
  loadFilterOptions();
  loadStats();
}

document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.add("hidden"));
    $("tab-" + tab.dataset.tab).classList.remove("hidden");
  });
});

$("bibtexSubmit").addEventListener("click", async () => {
  $("addError").textContent = ""; $("addSuccess").textContent = "";
  try {
    const res = await api("/papers", { method: "POST", body: JSON.stringify({ bibtex: $("bibtexInput").value, selected: currentPubSubtab === "selected" }) });
    $("addSuccess").textContent = res.message;
    $("bibtexInput").value = "";
    loadPapers(); loadFilterOptions(); loadStats();
  } catch (e) {
    $("addError").textContent = e.message;
  }
});

$("manualSubmit").addEventListener("click", async () => {
  $("addError").textContent = ""; $("addSuccess").textContent = "";
  const payload = {
    title: $("mTitle").value, authors: $("mAuthors").value, year: $("mYear").value,
    journal: $("mJournal").value, publisher: $("mPublisher").value, issn: $("mIssn").value,
    doi: $("mDoi").value, article_type: $("mType").value, impact_factor: $("mIF").value,
    quartile: $("mQuartile").value, selected: currentPubSubtab === "selected",
  };
  payload.complete_reference = `${payload.authors} (${payload.year}). ${payload.title}. ${payload.journal}.`;
  try {
    const res = await api("/papers", { method: "POST", body: JSON.stringify(payload) });
    $("addSuccess").textContent = res.message;
    document.querySelectorAll("#tab-manual input").forEach(i => i.value = "");
    $("mType").value = "Research Article";
    loadPapers(); loadFilterOptions(); loadStats();
  } catch (e) {
    $("addError").textContent = e.message;
  }
});

// ---------------- edit / delete / hide (publications) ----------------
function openEditModal(id) {
  const p = currentPapers.find(x => String(x.publication_id) === String(id));
  if (!p) return;
  eDomainEdited = false;
  $("eId").value = p.publication_id;
  $("eTitle").value = p.title || "";
  $("eAuthors").value = p.authors || "";
  $("eYear").value = p.year || "";
  $("eJournal").value = p.journal || "";
  $("ePublisher").value = p.publisher || "";
  $("eIssn").value = p.issn || "";
  $("eDoi").value = p.doi || "";
  $("eType").value = p.article_type || "";
  $("eIF").value = p.impact_factor || "";
  $("eQuartile").value = p.quartile || "";
  $("eNaasScore").value = p.naas_score || "";
  $("eField").value = p.field || "Interdisciplinary";
  $("eDomain").value = p.domain || "";
  $("eRef").value = p.complete_reference || "";
  $("eAbstract").value = p.abstract || "";
  $("eKeywords").value = p.keywords || "";
  $("editError").textContent = "";
  $("eCrossrefStatus").textContent = "";
  openModal("editModalBackdrop");
}

$("eDomain").addEventListener("input", () => { eDomainEdited = true; });
$("eField").addEventListener("change", () => { eDomainEdited = true; });

$("editSubmit").addEventListener("click", async () => {
  const id = $("eId").value;
  const payload = {
    title: $("eTitle").value, authors: $("eAuthors").value, year: $("eYear").value,
    journal: $("eJournal").value, publisher: $("ePublisher").value, issn: $("eIssn").value,
    doi: $("eDoi").value, article_type: $("eType").value, impact_factor: $("eIF").value,
    quartile: $("eQuartile").value, naas_score: $("eNaasScore").value, complete_reference: $("eRef").value,
    abstract: $("eAbstract").value, keywords: $("eKeywords").value,
  };
  if (eDomainEdited) {
    payload.domain = $("eDomain").value;
    payload.field = $("eField").value;
  }
  try {
    await api(`/papers/${id}`, { method: "PUT", body: JSON.stringify(payload) });
    closeModal("editModalBackdrop");
    loadPapers(); loadFilterOptions();
  } catch (e) {
    $("editError").textContent = e.message;
  }
});

$("eFetchCrossref").addEventListener("click", async () => {
  const id = $("eId").value;
  $("eCrossrefStatus").textContent = "Fetching from Crossref...";
  try {
    const res = await api(`/papers/${id}/enrich`, { method: "POST" });
    $("eAbstract").value = res.abstract || "";
    $("eKeywords").value = res.keywords || "";
    if (!eDomainEdited) {
      $("eDomain").value = res.domain || "";
      $("eField").value = res.field || "Interdisciplinary";
    }
    $("eCrossrefStatus").textContent = res.message;
  } catch (e) {
    $("eCrossrefStatus").textContent = e.message;
  }
});

$("enrichAllBtn").addEventListener("click", async () => {
  if (!confirm("Fetch abstracts for every paper with a DOI that doesn't have one yet? This calls the public Crossref API once per paper and may take a minute or two.")) return;
  $("enrichAllBtn").textContent = "Enriching...";
  $("enrichAllBtn").disabled = true;
  try {
    const res = await api("/papers/enrich-all", { method: "POST", body: JSON.stringify({ force: false }) });
    alert(res.message);
    loadPapers(); loadFilterOptions(); loadStats();
  } catch (e) {
    alert(e.message);
  } finally {
    $("enrichAllBtn").textContent = "Enrich All (Crossref)";
    $("enrichAllBtn").disabled = false;
  }
});

async function deletePaper(id) {
  if (!confirm("Delete this publication record?")) return;
  try {
    await api(`/papers/${id}`, { method: "DELETE" });
    loadPapers(); loadFilterOptions(); loadStats();
  } catch (e) {
    alert(e.message);
  }
}

async function toggleHidden(id) {
  try {
    await api(`/papers/${id}/toggle-hidden`, { method: "POST" });
    loadPapers();
  } catch (e) {
    alert(e.message);
  }
}

// ---------------- journal scores upload (NAAS + JCR, separately) ----------------
$("exportBackupBtn").addEventListener("click", async () => {
  try {
    const headers = {};
    if (authToken) headers["Authorization"] = "Bearer " + authToken;
    const res = await fetch(API_BASE + "/database/export-backup", { headers });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || "Could not export the database backup.");
    }
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "research_backup.db";
    document.body.appendChild(a); a.click(); a.remove();
    window.URL.revokeObjectURL(url);
    alert(
      "Downloaded. Save this as backend/research_backup.db in your project, then commit and push it. " +
      "This preserves EVERYTHING (not just NAAS/JCR — every publication, award, edit, hidden flag) across future redeploys."
    );
  } catch (e) {
    alert(e.message);
  }
});

$("exportSnapshotBtn").addEventListener("click", async () => {
  try {
    const headers = {};
    if (authToken) headers["Authorization"] = "Bearer " + authToken;
    const res = await fetch(API_BASE + "/journal-scores/export-snapshot", { headers });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || "Could not export the snapshot.");
    }
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "journal_scores_snapshot.json";
    document.body.appendChild(a); a.click(); a.remove();
    window.URL.revokeObjectURL(url);
    alert(
      "Downloaded. Save this as backend/journal_scores_snapshot.json in your project, then commit and push it. " +
      "The server will automatically reload it on every future startup, so this data survives redeploys."
    );
  } catch (e) {
    alert(e.message);
  }
});

$("resetScoresBtn").addEventListener("click", async () => {
  if (!confirm(
    "This resets every paper's Impact Factor and Quartile back to the original values from the CV, " +
    "clears all NAAS Scores, and wipes the journal scores table. Use this before re-doing a clean " +
    "NAAS + JCR upload. Continue?"
  )) return;
  try {
    const res = await api("/journal-scores/reset", { method: "POST" });
    alert(res.message);
    loadPapers(); loadFilterOptions(); loadStats();
  } catch (e) {
    alert(e.message);
  }
});

$("uploadNaasBtn").addEventListener("click", () => {
  $("naasError").textContent = ""; $("naasSuccess").textContent = "";
  openModal("naasModalBackdrop");
});

$("naasSubmit").addEventListener("click", async () => {
  $("naasError").textContent = ""; $("naasSuccess").textContent = "";
  const file = $("naasFile").files[0];
  if (!file) { $("naasError").textContent = "Choose the NAAS Score PDF first."; return; }
  const fd = new FormData();
  fd.append("file", file);
  $("naasSubmit").textContent = "Uploading..."; $("naasSubmit").disabled = true;
  try {
    const res = await apiUpload("/journal-scores/upload-naas", fd);
    $("naasSuccess").textContent = res.message;
    loadPapers(); loadFilterOptions(); loadStats();
  } catch (e) {
    $("naasError").textContent = e.message;
  } finally {
    $("naasSubmit").textContent = "Upload & Apply"; $("naasSubmit").disabled = false;
  }
});

$("uploadJcrBtn").addEventListener("click", () => {
  $("jcrError").textContent = ""; $("jcrSuccess").textContent = "";
  openModal("jcrModalBackdrop");
});

$("jcrSubmit").addEventListener("click", async () => {
  $("jcrError").textContent = ""; $("jcrSuccess").textContent = "";
  const file = $("jcrFile").files[0];
  if (!file) { $("jcrError").textContent = "Choose the JCR Impact Factor PDF first."; return; }
  const fd = new FormData();
  fd.append("file", file);
  $("jcrSubmit").textContent = "Starting..."; $("jcrSubmit").disabled = true;
  try {
    const start = await apiUpload("/journal-scores/upload-jcr", fd);
    $("jcrSuccess").textContent = "Processing in the background — this can take a few minutes. You can leave this open; it'll update automatically.";
    await pollJcrJob(start.job_id);
  } catch (e) {
    $("jcrError").textContent = e.message;
    $("jcrSubmit").textContent = "Upload & Apply"; $("jcrSubmit").disabled = false;
  }
});

async function pollJcrJob(jobId) {
  const poll = async () => {
    try {
      const job = await api(`/journal-scores/upload-status/${jobId}`);
      if (job.status === "processing") {
        $("jcrSubmit").textContent = "Processing...";
        setTimeout(poll, 4000);
        return;
      }
      if (job.status === "error") {
        $("jcrError").textContent = job.message;
        $("jcrSuccess").textContent = "";
      } else {
        $("jcrSuccess").textContent = job.message;
        loadPapers(); loadFilterOptions(); loadStats();
      }
      $("jcrSubmit").textContent = "Upload & Apply"; $("jcrSubmit").disabled = false;
    } catch (e) {
      $("jcrError").textContent = e.message;
      $("jcrSubmit").textContent = "Upload & Apply"; $("jcrSubmit").disabled = false;
    }
  };
  poll();
}

// ---------------- CV download ----------------
const CV_SECTIONS = {
  "publications": {
    endpoint: "/papers?sort=year_desc", idField: "publication_id",
    label: p => `${escapeHtml(p.title)}`,
    meta: p => `${escapeHtml(p.authors)}${p.journal ? " &middot; " + escapeHtml(p.journal) : ""} &middot; ${escapeHtml(p.year || "")}`,
  },
  "awards": {
    endpoint: "/awards", idField: "award_id",
    label: a => escapeHtml(a.title),
    meta: a => `${escapeHtml(a.awarding_body)} &middot; ${escapeHtml(a.year)}`,
  },
  "projects": {
    endpoint: "/projects", idField: "project_id",
    label: pr => escapeHtml(pr.project_title),
    meta: pr => `${escapeHtml(pr.funding_agency)} &middot; ${escapeHtml(pr.date_start)}`,
  },
  "book-chapters": {
    endpoint: "/book-chapters", idField: "book_chapter_id",
    label: b => escapeHtml(b.title),
    meta: b => `${escapeHtml(b.book_title)} &middot; ${escapeHtml(b.year)}`,
  },
  "software": {
    endpoint: "/software", idField: "software_id",
    label: s => escapeHtml(s.package_name),
    meta: s => `${escapeHtml(s.year)}`,
  },
};

async function loadCvSections() {
  for (const [key, cfg] of Object.entries(CV_SECTIONS)) {
    const container = $(`cvList_${key}`);
    container.innerHTML = `<p class="cv-item-meta">Loading...</p>`;
    try {
      const items = await api(cfg.endpoint);
      container.innerHTML = items.length ? items.map(it => `
        <label class="cv-item-option">
          <input type="checkbox" class="cv-item-checkbox" data-section="${key}" data-id="${it[cfg.idField]}" checked>
          <span><strong>${cfg.label(it)}</strong><br><span class="cv-item-meta">${cfg.meta(it)}</span></span>
        </label>
      `).join("") : `<p class="cv-item-meta">Nothing here yet.</p>`;
      updateSectionToggleState(key);
      container.querySelectorAll(".cv-item-checkbox").forEach(cb => {
        cb.addEventListener("change", () => updateSectionToggleState(key));
      });
    } catch (e) {
      container.innerHTML = `<p class="cv-item-meta">Could not load.</p>`;
    }
  }
}

function updateSectionToggleState(section) {
  const boxes = document.querySelectorAll(`.cv-item-checkbox[data-section="${section}"]`);
  const toggle = document.querySelector(`.cv-section-toggle[data-section="${section}"]`);
  if (!toggle || !boxes.length) return;
  toggle.checked = Array.from(boxes).every(b => b.checked);
}

document.querySelectorAll(".cv-section-toggle").forEach(toggle => {
  toggle.addEventListener("change", () => {
    const section = toggle.dataset.section;
    document.querySelectorAll(`.cv-item-checkbox[data-section="${section}"]`).forEach(cb => {
      cb.checked = toggle.checked;
    });
  });
});

$("cvSelectAllBtn").addEventListener("click", () => {
  document.querySelectorAll(".cv-item-checkbox").forEach(cb => { cb.checked = true; });
  document.querySelectorAll(".cv-section-toggle").forEach(t => { t.checked = true; });
});

$("cvClearAllBtn").addEventListener("click", () => {
  document.querySelectorAll(".cv-item-checkbox").forEach(cb => { cb.checked = false; });
  document.querySelectorAll(".cv-section-toggle").forEach(t => { t.checked = false; });
});

$("downloadCvBtn").addEventListener("click", () => {
  $("cvError").textContent = "";
  openModal("cvModalBackdrop");
  loadCvSections();
});

$("cvGenerateBtn").addEventListener("click", async () => {
  $("cvError").textContent = "";
  const payload = {};
  for (const key of Object.keys(CV_SECTIONS)) {
    const ids = Array.from(document.querySelectorAll(`.cv-item-checkbox[data-section="${key}"]:checked`))
      .map(cb => cb.dataset.id);
    if (ids.length) payload[key] = ids;
  }
  if (Object.keys(payload).length === 0) {
    $("cvError").textContent = "Select at least one item first.";
    return;
  }

  $("cvGenerateBtn").textContent = "Generating..."; $("cvGenerateBtn").disabled = true;
  try {
    const headers = { "Content-Type": "application/json" };
    if (authToken) headers["Authorization"] = "Bearer " + authToken;
    const res = await fetch(API_BASE + "/cv/download", {
      method: "POST", headers, body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || "Could not generate the CV.");
    }
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "Md_Yeasin_CV.pdf";
    document.body.appendChild(a); a.click(); a.remove();
    window.URL.revokeObjectURL(url);
    closeModal("cvModalBackdrop");
  } catch (e) {
    $("cvError").textContent = e.message;
  } finally {
    $("cvGenerateBtn").textContent = "Generate & Download"; $("cvGenerateBtn").disabled = false;
  }
});

// ---------------- generic record CRUD: Awards / Projects / Book Chapters / Software ----------------
const RECORD_SCHEMAS = {
  "awards": {
    idField: "award_id",
    label: "Award",
    fields: [
      { key: "title", label: "Title" },
      { key: "awarding_body", label: "Awarding Body" },
      { key: "year", label: "Year" },
      { key: "description", label: "Description", full: true },
    ],
  },
  "projects": {
    idField: "project_id",
    label: "Project",
    fields: [
      { key: "sl_no", label: "SL No." },
      { key: "investigators", label: "Investigators", full: true },
      { key: "project_title", label: "Project Title", full: true },
      { key: "funding_agency", label: "Funding Agency" },
      { key: "date_start", label: "Start Date" },
      { key: "status", label: "Status" },
    ],
  },
  "book-chapters": {
    idField: "book_chapter_id",
    label: "Book Chapter",
    fields: [
      { key: "title", label: "Chapter Title", full: true },
      { key: "authors", label: "Authors", full: true },
      { key: "book_title", label: "Book Title" },
      { key: "publisher", label: "Publisher" },
      { key: "year", label: "Year" },
      { key: "pages", label: "Pages" },
      { key: "isbn", label: "ISBN" },
      { key: "doi", label: "DOI", full: true },
    ],
  },
  "software": {
    idField: "software_id",
    label: "Software / Package",
    fields: [
      { key: "package_name", label: "Package Name" },
      { key: "year", label: "Year" },
      { key: "reference", label: "Reference", full: true },
      { key: "downloads", label: "Downloads" },
      { key: "cran_url", label: "CRAN URL", full: true },
    ],
  },
};

function recordTagsHtml(item) {
  return item.hidden ? `<span class="tag tag-hidden">Hidden</span>` : "";
}

function recordActionsHtml(type, id, hidden) {
  return `
    <div class="record-actions admin-actions ${authToken ? "visible" : ""}">
      <button class="icon-btn" data-record-edit="${type}" data-id="${id}">Edit</button>
      <button class="icon-btn" data-record-toggle-hidden="${type}" data-id="${id}">${hidden ? "Show" : "Hide"}</button>
      <button class="icon-btn danger" data-record-delete="${type}" data-id="${id}">Delete</button>
    </div>`;
}

function renderAwards(items) {
  $("awardsList").innerHTML = items.length ? items.map(it => `
    <div class="record-entry" data-id="${it.award_id}">
      <div class="record-main">
        <h3 class="record-title">${escapeHtml(it.title)}</h3>
        <div class="record-meta">${escapeHtml(it.awarding_body)} &middot; ${escapeHtml(it.year)}${it.description ? " &middot; " + escapeHtml(it.description) : ""} ${recordTagsHtml(it)}</div>
      </div>
      ${recordActionsHtml("awards", it.award_id, it.hidden)}
    </div>
  `).join("") : `<div class="empty-state">No awards yet.</div>`;
  wireRecordButtons("awards", items, "award_id");
}

function renderProjects(items) {
  $("projectsList").innerHTML = items.length ? items.map(it => `
    <div class="record-entry" data-id="${it.project_id}">
      <div class="record-main">
        <h3 class="record-title">${escapeHtml(it.project_title)}</h3>
        <div class="record-meta">${escapeHtml(it.investigators)}</div>
        <div class="record-meta">${escapeHtml(it.funding_agency)} &middot; Started ${escapeHtml(it.date_start)} &middot; ${escapeHtml(it.status)} ${recordTagsHtml(it)}</div>
      </div>
      ${recordActionsHtml("projects", it.project_id, it.hidden)}
    </div>
  `).join("") : `<div class="empty-state">No projects yet.</div>`;
  wireRecordButtons("projects", items, "project_id");
}

function renderBookChapters(items) {
  $("bookChaptersList").innerHTML = items.length ? items.map(it => `
    <div class="record-entry" data-id="${it.book_chapter_id}">
      <div class="record-main">
        <h3 class="record-title">${escapeHtml(it.title)}</h3>
        <div class="record-meta">${escapeHtml(it.authors)}</div>
        <div class="record-meta">${escapeHtml(it.book_title)}${it.publisher ? ", " + escapeHtml(it.publisher) : ""} &middot; ${escapeHtml(it.year)}${it.pages ? " &middot; pp. " + escapeHtml(it.pages) : ""}${it.doi ? ` &middot; <a href="${it.doi.startsWith("http") ? it.doi : "https://doi.org/" + it.doi}" target="_blank" rel="noopener">${escapeHtml(it.doi)}</a>` : ""} ${recordTagsHtml(it)}</div>
      </div>
      ${recordActionsHtml("book-chapters", it.book_chapter_id, it.hidden)}
    </div>
  `).join("") : `<div class="empty-state">No book chapters added yet.</div>`;
  wireRecordButtons("book-chapters", items, "book_chapter_id");
}

function renderSoftware(items) {
  $("softwareList").innerHTML = items.length ? items.map(it => `
    <div class="record-entry" data-id="${it.software_id}">
      <div class="record-main">
        <h3 class="record-title">${escapeHtml(it.package_name)}</h3>
        <div class="record-meta">${escapeHtml(it.reference)}</div>
        <div class="record-meta">${escapeHtml(it.year)}${it.downloads ? " &middot; " + escapeHtml(it.downloads) + " downloads" : ""}${it.cran_url ? ` &middot; <a href="${escapeHtml(it.cran_url)}" target="_blank" rel="noopener">CRAN</a>` : ""} ${recordTagsHtml(it)}</div>
      </div>
      ${recordActionsHtml("software", it.software_id, it.hidden)}
    </div>
  `).join("") : `<div class="empty-state">No software packages yet.</div>`;
  wireRecordButtons("software", items, "software_id");
}

function wireRecordButtons(type, items, idField) {
  document.querySelectorAll(`[data-record-edit="${type}"]`).forEach(b => {
    b.addEventListener("click", () => openRecordModal(type, b.dataset.id, items));
  });
  document.querySelectorAll(`[data-record-delete="${type}"]`).forEach(b => {
    b.addEventListener("click", () => deleteRecord(type, b.dataset.id));
  });
  document.querySelectorAll(`[data-record-toggle-hidden="${type}"]`).forEach(b => {
    b.addEventListener("click", () => toggleRecordHidden(type, b.dataset.id));
  });
}

async function toggleRecordHidden(type, id) {
  try {
    await api(`/${type}/${id}/toggle-hidden`, { method: "POST" });
    loadSection(type);
  } catch (e) {
    alert(e.message);
  }
}

document.querySelectorAll(".add-record-btn").forEach(btn => {
  btn.addEventListener("click", () => openRecordModal(btn.dataset.type, null, []));
});

function openRecordModal(type, id, items) {
  const schema = RECORD_SCHEMAS[type];
  const record = id ? items.find(it => String(it[schema.idField]) === String(id)) : null;
  $("recordModalTitle").textContent = id ? `Edit ${schema.label}` : `Add ${schema.label}`;
  $("recordId").value = id || "";
  $("recordType").value = type;
  $("recordError").textContent = "";
  $("recordFormGrid").innerHTML = schema.fields.map(f => `
    <div style="${f.full ? "grid-column: 1 / -1;" : ""}">
      <label for="r_${f.key}">${escapeHtml(f.label)}</label>
      <input id="r_${f.key}" value="${escapeHtml(record ? record[f.key] : "")}">
    </div>
  `).join("");
  openModal("recordModalBackdrop");
}

$("recordSubmit").addEventListener("click", async () => {
  const type = $("recordType").value;
  const id = $("recordId").value;
  const schema = RECORD_SCHEMAS[type];
  const payload = {};
  schema.fields.forEach(f => { payload[f.key] = $(`r_${f.key}`).value; });
  try {
    if (id) {
      await api(`/${type}/${id}`, { method: "PUT", body: JSON.stringify(payload) });
    } else {
      await api(`/${type}`, { method: "POST", body: JSON.stringify(payload) });
    }
    closeModal("recordModalBackdrop");
    loadSection(type);
  } catch (e) {
    $("recordError").textContent = e.message;
  }
});

async function deleteRecord(type, id) {
  if (!confirm("Delete this record?")) return;
  try {
    await api(`/${type}/${id}`, { method: "DELETE" });
    loadSection(type);
  } catch (e) {
    alert(e.message);
  }
}

// ---------------- init ----------------
(async function init() {
  await loadProfile();
  await loadFilterOptions();
  await loadStats();
  await loadPapers();
})();
