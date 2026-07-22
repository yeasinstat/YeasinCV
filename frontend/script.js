const API_BASE = "/api";

let authToken = null;
let currentPapers = [];
let filterOptions = { domains: [] };
let selectedDomains = new Set();
let eDomainEdited = false;
let currentSection = "publications";

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
async function loadProfile() {
  try {
    const s = await api("/scientist");
    $("scientistCard").querySelector(".scientist-name").textContent = s.name;
    $("scientistCard").querySelector(".scientist-role").textContent =
      `${s.designation} · ${s.institute.split("(")[1]?.replace(")", "") || s.institute}`;

    $("pName").textContent = s.name;
    $("pRole").textContent = `${s.designation} · ${s.institute}`;
    $("pAddress").textContent = s.address || "";
    const contactBits = [];
    if (s.dob) contactBits.push(`DOB: ${s.dob}`);
    if (s.mobile && s.mobile.length) contactBits.push(`Mobile: ${s.mobile.join(" / ")}`);
    if (s.email && s.email.length) contactBits.push(`Email: ${s.email.join(", ")}`);
    $("pContact").innerHTML = contactBits.map(b => `<span>${escapeHtml(b)}</span>`).join("");
    $("pInterest").textContent = s.research_interest || "";

    $("pEducation").innerHTML = (s.education || [])
      .map(e => `<li><strong>${escapeHtml(e.degree)}</strong> (${escapeHtml(e.year)}) &middot; ${escapeHtml(e.institution)}</li>`)
      .join("");
    $("pAccolades").innerHTML = (s.accolades || [])
      .map(a => `<li>${escapeHtml(a)}</li>`)
      .join("");
    $("pEmployment").innerHTML = (s.employment || [])
      .map(e => `<li><strong>${escapeHtml(e.period)}</strong> &middot; ${escapeHtml(e.role)}, ${escapeHtml(e.institution)}</li>`)
      .join("");
    $("pOtherRecords").innerHTML = (s.other_records || [])
      .map(r => `<li>${escapeHtml(r)}</li>`)
      .join("");
  } catch (e) { /* backend not reachable yet — keep defaults */ }
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

async function loadPapers() {
  const meta = $("resultsMeta");
  meta.textContent = "Loading...";
  try {
    const query = buildQuery();
    const papers = await api("/papers?" + query);
    currentPapers = papers;
    renderPapers(papers);
    meta.textContent = `${papers.length} publication${papers.length !== 1 ? "s" : ""} found`;
  } catch (e) {
    $("paperList").innerHTML = `<div class="empty-state">Could not load records. Is the backend running at ${API_BASE}?</div>`;
    meta.textContent = "";
  }
}

function renderPapers(papers) {
  const list = $("paperList");
  if (!papers.length) {
    list.innerHTML = `<div class="empty-state">No publications match these filters.</div>`;
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
        <div class="paper-meta">${escapeHtml(p.authors)}${p.journal ? " &middot; " + escapeHtml(p.journal) : ""}</div>
        <div class="paper-tags">
          ${domainTags}
          ${p.field ? `<span class="tag tag-domain">${escapeHtml(p.field)}</span>` : ""}
          ${p.quartile ? `<span class="tag tag-quartile-${p.quartile}">${escapeHtml(p.quartile)}</span>` : ""}
          ${p.hidden ? `<span class="tag tag-hidden">Hidden</span>` : ""}
          ${p.doi ? `<span class="paper-doi"><a href="${p.doi.startsWith("http") ? p.doi : "https://doi.org/" + p.doi}" target="_blank" rel="noopener">${escapeHtml(p.doi)}</a></span>` : ""}
        </div>
      </div>
      <div class="paper-side">
        <div class="paper-year">${escapeHtml(p.year || "—")}</div>
        ${p.impact_factor ? `<div class="paper-if">IF ${escapeHtml(p.impact_factor)}</div>` : ""}
        <div class="admin-actions ${authToken ? "visible" : ""}">
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

// ---------------- add publication button (injected) ----------------
const addBtn = document.createElement("button");
addBtn.textContent = "+ Add Publication";
addBtn.className = "btn-ghost add-publication-btn hidden";
$("scientistCard").insertBefore(addBtn, $("adminBtn"));
addBtn.addEventListener("click", () => {
  $("addError").textContent = ""; $("addSuccess").textContent = "";
  openModal("addModalBackdrop");
});

function onAuthChange() {
  const visible = !!authToken;
  addBtn.classList.toggle("hidden", !visible);
  $("enrichAllBtn").classList.toggle("hidden", !visible);
  $("uploadScoresBtn").classList.toggle("hidden", !visible);
  document.querySelectorAll(".add-record-btn").forEach(b => b.classList.toggle("hidden", !visible));
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
    const res = await api("/papers", { method: "POST", body: JSON.stringify({ bibtex: $("bibtexInput").value }) });
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
    quartile: $("mQuartile").value,
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
    quartile: $("eQuartile").value, complete_reference: $("eRef").value,
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

// ---------------- journal scores upload ----------------
$("uploadScoresBtn").addEventListener("click", () => {
  $("scoresError").textContent = ""; $("scoresSuccess").textContent = "";
  openModal("scoresModalBackdrop");
});

$("scoresSubmit").addEventListener("click", async () => {
  $("scoresError").textContent = ""; $("scoresSuccess").textContent = "";
  const file = $("scoresFile").files[0];
  if (!file) { $("scoresError").textContent = "Choose an .xlsx file first."; return; }
  const fd = new FormData();
  fd.append("file", file);
  try {
    const res = await apiUpload("/journal-scores/upload", fd);
    $("scoresSuccess").textContent = res.message;
    loadPapers(); loadFilterOptions(); loadStats();
  } catch (e) {
    $("scoresError").textContent = e.message;
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
