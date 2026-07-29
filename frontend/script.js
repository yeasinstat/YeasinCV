const API_BASE = "/api";

let authToken = null;
let sessionRole = null; // "super_admin" or "scientist"
let sessionScientistId = null; // set when sessionRole === "scientist"
let loginEntryPoint = null; // "admin" or "user" — tracks which button was used to log in
let currentScientistId = parseInt(localStorage.getItem("currentScientistId") || "1", 10) || 1;
let allScientists = [];
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

// Endpoints that are NOT specific to one scientist's profile — skip auto-injecting scientist_id
const SCIENTIST_SCOPE_SKIP = ["/login", "/verify-otp", "/scientists", "/journal-scores", "/database"];

function withScientistId(path) {
  if (SCIENTIST_SCOPE_SKIP.some(skip => path.startsWith(skip))) return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}scientist_id=${currentScientistId}`;
}

async function api(path, options = {}) {
  const headers = options.headers || {};
  if (options.body) headers["Content-Type"] = "application/json";
  if (authToken) headers["Authorization"] = "Bearer " + authToken;
  const res = await fetch(API_BASE + withScientistId(path), { ...options, headers });
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
const HOME_BLOCK_ORDER = ["header", "research_interest", "current_work", "research_team"];
const PERSONAL_BLOCK_ORDER = ["education", "accolades", "employment", "other_records"];
let profileLayout = {}; // { block_order: [...], hidden_blocks: [...], items: { education: { order: [...], hidden: [...] } } }
let scientistData = null;
let researchTeamData = [];

async function loadProfile() {
  try {
    scientistData = await api("/scientist");
    const s = scientistData;
    $("scientistCard").querySelector(".scientist-name").textContent = s.name;
    $("scientistCard").querySelector(".scientist-role").textContent =
      `${s.designation} · ${s.institute.split("(")[1]?.replace(")", "") || s.institute}`;

    try { profileLayout = await api("/profile-layout"); } catch { profileLayout = {}; }
    try { researchTeamData = await api("/research-team"); } catch { researchTeamData = []; }
    renderProfileBlocks("profileBlocks", HOME_BLOCK_ORDER);
    renderProfileBlocks("personalDetailsBlocks", PERSONAL_BLOCK_ORDER);
  } catch (e) { /* backend not reachable yet */ }
}

async function reloadResearchTeam() {
  try { researchTeamData = await api("/research-team"); } catch { researchTeamData = []; }
  renderProfileBlocks("profileBlocks", HOME_BLOCK_ORDER);
}

function renderProfileBlocks(containerId, blockIds) {
  const s = scientistData;
  if (!s) return;
  const container = $(containerId);
  if (!container) return;
  const isAdmin = !!authToken;
  const fullBlockOrder = profileLayout.block_order || [...HOME_BLOCK_ORDER, ...PERSONAL_BLOCK_ORDER];
  const blockOrder = fullBlockOrder.filter(id => blockIds.includes(id));
  // include any block from this group not yet in the saved order (e.g. newly added block types)
  blockIds.forEach(id => { if (!blockOrder.includes(id)) blockOrder.push(id); });
  const hiddenBlocks = new Set(profileLayout.hidden_blocks || []);
  const items = profileLayout.items || {};
  // cv_blocks/cv_items: undefined/null means "everything included" (default state)
  const cvBlocksSet = profileLayout.cv_blocks ? new Set(profileLayout.cv_blocks) : null;
  const isBlockCvIncluded = (id) => cvBlocksSet === null ? true : cvBlocksSet.has(id);
  const cvItemsCfg = profileLayout.cv_items || {};
  const isItemCvIncluded = (key, idx) => {
    const cfg = cvItemsCfg[key];
    return cfg === undefined ? true : cfg.includes(idx);
  };

  const blockRenderers = {
    header: () => {
      const emailText = (s.email || []).join(", ");
      const inner = `
        <div class="block-header-inner">
          <div class="block-photo-col">
            <img src="${escapeHtml(s.photo_filename || 'yeasin-photo.png')}" alt="Photo of ${escapeHtml(s.name)}" class="block-photo" onerror="this.src='yeasin-photo.png'">
            <div class="block-links">
              ${s.scholar_url ? `<a href="${escapeHtml(s.scholar_url)}" target="_blank" rel="noopener" class="block-link-btn"><i class="fas fa-graduation-cap"></i>
                <span>Google Scholar</span></a>` : ""}
              ${s.linkedin_url ? `<a href="${escapeHtml(s.linkedin_url)}" target="_blank" rel="noopener" class="block-link-btn"><i class="fab fa-linkedin"></i>
                <span>LinkedIn</span></a>` : ""}
            </div>
          </div>
          <div>
            <h1 class="block-name">${escapeHtml(s.name)}</h1>
            <p class="block-role">${escapeHtml(s.designation)} &middot; ${escapeHtml(s.institute)}</p>
            <p class="block-address">Email: ${escapeHtml(emailText)}</p>
          </div>
        </div>`;
      return { title: "", html: inner };
    },

    research_interest: () => renderListBlock("Research Interest", s.research_interest || [], "research_interest",
      r => escapeHtml(r)),

    current_work: () => renderListBlock("Current Work", s.current_work || [], "current_work",
      r => escapeHtml(r)),

    research_team: () => renderTeamBlock(),

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
      const cvOn = isItemCvIncluded(key, idx);
      return `<li class="block-list-item${hidden ? " item-hidden" : ""}" data-item-idx="${idx}">
        <span class="item-drag-handle" title="Drag to reorder">⠿</span>
        <label class="cv-tick" title="Include in CV">
          <input type="checkbox" class="item-cv-checkbox" data-block="${key}" data-idx="${idx}" ${cvOn ? "checked" : ""}>
        </label>
        <span class="item-text">${renderFn(dataItems[idx])}</span>
        <button class="item-toggle-btn" data-block="${key}" data-idx="${idx}">${hidden ? "Show" : "Hide"}</button>
      </li>`;
    }).join("");

    return { title, html: `<ul class="block-list" data-block-key="${key}">${listHtml}</ul>` };
  }

  function renderTeamBlock() {
    const cards = researchTeamData.map(m => {
      if (m.hidden && !isAdmin) return "";
      return `<div class="team-card${m.hidden ? " item-hidden" : ""}" data-member-id="${m.member_id}">
        ${isAdmin ? `<span class="item-drag-handle team-drag-handle" title="Drag to reorder">⠿</span>` : ""}
        <div class="team-photo-wrap">
          <img src="${escapeHtml(m.photo_filename || 'yeasin-photo.png')}" alt="Photo of ${escapeHtml(m.name)}" class="team-photo" onerror="this.src='yeasin-photo.png'">
          ${isAdmin ? `<label class="team-photo-upload-btn">Change Photo<input type="file" accept=".png,.jpg,.jpeg,.webp" class="team-photo-input" data-member-id="${m.member_id}" hidden></label>` : ""}
        </div>
        <div class="team-name">${escapeHtml(m.name)}</div>
        <div class="team-designation">${escapeHtml(m.designation || "")}</div>
        ${isAdmin ? `<div class="team-card-actions">
          <button class="icon-btn" data-team-edit="${m.member_id}">Edit</button>
          <button class="icon-btn" data-team-toggle-hidden="${m.member_id}">${m.hidden ? "Show" : "Hide"}</button>
          <button class="icon-btn danger" data-team-delete="${m.member_id}">Delete</button>
        </div>` : ""}
      </div>`;
    }).join("");
    const addBtn = isAdmin ? `<button type="button" class="btn-secondary" id="addTeamMemberBtn">+ Add Team Member</button>` : "";
    if (!researchTeamData.length && !isAdmin) return { title: "", html: "" };
    return { title: "Research Team", html: `<div class="team-grid" id="teamGrid">${cards}</div>${addBtn}` };
  }

  let html = "";
  for (const blockId of blockOrder) {
    const renderer = blockRenderers[blockId];
    if (!renderer) continue;
    const isHidden = hiddenBlocks.has(blockId);
    if (isHidden && !isAdmin) continue;
    const { title, html: content } = renderer();
    const cvOn = isBlockCvIncluded(blockId);

    html += `<div class="profile-block${isHidden ? " block-hidden" : ""}" data-block-id="${blockId}">
      ${title || isAdmin ? `<div class="profile-block-header">
        <h3 class="profile-block-title">${escapeHtml(title)}</h3>
        <div class="profile-block-admin">
          <label class="cv-tick" title="Include in CV">
            <input type="checkbox" class="block-cv-checkbox" data-block="${blockId}" ${cvOn ? "checked" : ""}>
          </label>
          <span class="block-drag-handle" title="Drag to reorder">⠿</span>
          <button class="block-edit-btn" data-edit-block="${blockId}">Edit</button>
          <button class="block-toggle-btn" data-block="${blockId}">${isHidden ? "Show" : "Hide"}</button>
        </div>
      </div>` : (isAdmin ? `<div class="profile-block-header" style="border-bottom:none; margin-bottom:4px; padding-bottom:0;">
        <span></span>
        <div class="profile-block-admin">
          <label class="cv-tick" title="Include in CV">
            <input type="checkbox" class="block-cv-checkbox" data-block="${blockId}" ${cvOn ? "checked" : ""}>
          </label>
          <span class="block-drag-handle" title="Drag to reorder">⠿</span>
          <button class="block-edit-btn" data-edit-block="${blockId}">Edit</button>
          <button class="block-toggle-btn" data-block="${blockId}">${isHidden ? "Show" : "Hide"}</button>
        </div>
      </div>` : "")}
      ${content}
    </div>`;
  }
  container.innerHTML = html;

  // Add admin-logged-in class for CSS-based admin control visibility
  document.body.classList.toggle("admin-logged-in", isAdmin);

  // Wire up block edit buttons
  container.querySelectorAll(".block-edit-btn").forEach(btn => {
    btn.addEventListener("click", () => openBlockEditModal(btn.dataset.editBlock));
  });

  // Wire up block hide/show buttons
  container.querySelectorAll(".block-toggle-btn").forEach(btn => {
    btn.addEventListener("click", () => toggleBlock(btn.dataset.block));
  });

  // Wire up item hide/show buttons
  container.querySelectorAll(".item-toggle-btn").forEach(btn => {
    btn.addEventListener("click", () => toggleItem(btn.dataset.block, parseInt(btn.dataset.idx)));
  });

  // Wire up block CV checkboxes
  container.querySelectorAll(".block-cv-checkbox").forEach(cb => {
    cb.addEventListener("change", () => toggleBlockCv(cb.dataset.block));
  });

  // Wire up item CV checkboxes
  container.querySelectorAll(".item-cv-checkbox").forEach(cb => {
    cb.addEventListener("change", () => toggleItemCv(cb.dataset.block, parseInt(cb.dataset.idx)));
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

    // Research Team: its own drag-reorder (writes to the DB, not profileLayout)
    const teamGrid = container.querySelector("#teamGrid");
    if (teamGrid) {
      new Sortable(teamGrid, {
        animation: 150,
        handle: ".team-drag-handle",
        ghostClass: "sortable-ghost",
        onEnd: async () => {
          const order = [...teamGrid.querySelectorAll(".team-card")].map(el => parseInt(el.dataset.memberId));
          try { await api("/research-team/reorder", { method: "PUT", body: JSON.stringify({ order }) }); } catch (e) { console.error(e); }
        },
      });
    }
  }

  // Research Team button wiring (works whether admin drag is active or not)
  container.querySelectorAll("[data-team-edit]").forEach(btn => {
    btn.addEventListener("click", () => openTeamMemberModal(parseInt(btn.dataset.teamEdit)));
  });
  container.querySelectorAll("[data-team-delete]").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm("Remove this team member?")) return;
      try {
        await api(`/research-team/${btn.dataset.teamDelete}`, { method: "DELETE" });
        await reloadResearchTeam();
      } catch (e) { alert(e.message); }
    });
  });
  container.querySelectorAll("[data-team-toggle-hidden]").forEach(btn => {
    btn.addEventListener("click", async () => {
      try {
        await api(`/research-team/${btn.dataset.teamToggleHidden}/toggle-hidden`, { method: "POST" });
        await reloadResearchTeam();
      } catch (e) { alert(e.message); }
    });
  });
  container.querySelectorAll(".team-photo-input").forEach(input => {
    input.addEventListener("change", async () => {
      if (!input.files[0]) return;
      const fd = new FormData();
      fd.append("file", input.files[0]);
      try {
        await apiUpload(`/research-team/${input.dataset.memberId}/photo?scientist_id=${currentScientistId}`, fd);
        await reloadResearchTeam();
      } catch (e) { alert(e.message); }
    });
  });
  const addTeamBtn = container.querySelector("#addTeamMemberBtn");
  if (addTeamBtn) addTeamBtn.addEventListener("click", () => openTeamMemberModal(null));
}

function toggleBlockCv(blockId) {
  // Materialize the "everything included" default into an explicit list the first time anything is toggled
  if (!profileLayout.cv_blocks) {
    profileLayout.cv_blocks = DEFAULT_BLOCK_ORDER.slice();
  }
  const set = new Set(profileLayout.cv_blocks);
  if (set.has(blockId)) set.delete(blockId); else set.add(blockId);
  profileLayout.cv_blocks = [...set];
  saveLayout();
}

function toggleItemCv(blockKey, idx) {
  if (!profileLayout.cv_items) profileLayout.cv_items = {};
  if (!profileLayout.cv_items[blockKey]) {
    // Materialize default (all current items included) before toggling one off
    const s = scientistData;
    const dataMap = { education: s.education, accolades: s.accolades, employment: s.employment, other_records: s.other_records };
    const len = (dataMap[blockKey] || []).length;
    profileLayout.cv_items[blockKey] = Array.from({ length: len }, (_, i) => i);
  }
  const set = new Set(profileLayout.cv_items[blockKey]);
  if (set.has(idx)) set.delete(idx); else set.add(idx);
  profileLayout.cv_items[blockKey] = [...set];
  saveLayout();
}

function toggleBlock(blockId) {
  const hidden = new Set(profileLayout.hidden_blocks || []);
  if (hidden.has(blockId)) hidden.delete(blockId); else hidden.add(blockId);
  profileLayout.hidden_blocks = [...hidden];
  saveLayout();
  renderProfileBlocks("profileBlocks", HOME_BLOCK_ORDER);
  renderProfileBlocks("personalDetailsBlocks", PERSONAL_BLOCK_ORDER);
}

function toggleItem(blockKey, idx) {
  if (!profileLayout.items) profileLayout.items = {};
  if (!profileLayout.items[blockKey]) profileLayout.items[blockKey] = {};
  const hidden = new Set(profileLayout.items[blockKey].hidden || []);
  if (hidden.has(idx)) hidden.delete(idx); else hidden.add(idx);
  profileLayout.items[blockKey].hidden = [...hidden];
  saveLayout();
  renderProfileBlocks("profileBlocks", HOME_BLOCK_ORDER);
  renderProfileBlocks("personalDetailsBlocks", PERSONAL_BLOCK_ORDER);
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

// ---------------- Home content editing ----------------
const LIST_BLOCK_SCHEMAS = {
  research_interest: { title: "Edit Research Interest", fields: [
    { key: "_value", label: "Research Interest Point" },
  ] },
  current_work: { title: "Edit Current Work", fields: [
    { key: "_value", label: "Current Work Point" },
  ] },
  education: { title: "Edit Education", fields: [
    { key: "degree", label: "Degree" }, { key: "year", label: "Year" }, { key: "institution", label: "Institution" },
  ] },
  employment: { title: "Edit Employment", fields: [
    { key: "period", label: "Period" }, { key: "role", label: "Role" }, { key: "institution", label: "Institution" },
  ] },
  accolades: { title: "Edit Academic Accolades", fields: [
    { key: "_value", label: "Accolade" },
  ] },
  other_records: { title: "Edit Other Records", fields: [
    { key: "_value", label: "Record" },
  ] },
};

let editingTeamMemberId = null;
function openTeamMemberModal(memberId) {
  editingTeamMemberId = memberId;
  $("teamMemberError").textContent = "";
  if (memberId) {
    const m = researchTeamData.find(x => x.member_id === memberId);
    $("teamMemberModalTitle").textContent = "Edit Team Member";
    $("tmName").value = m ? m.name : "";
    $("tmDesignation").value = m ? m.designation : "";
  } else {
    $("teamMemberModalTitle").textContent = "Add Team Member";
    $("tmName").value = ""; $("tmDesignation").value = "";
  }
  openModal("teamMemberModalBackdrop");
}

$("teamMemberSubmit").addEventListener("click", async () => {
  $("teamMemberError").textContent = "";
  const payload = { name: $("tmName").value, designation: $("tmDesignation").value };
  try {
    if (editingTeamMemberId) {
      await api(`/research-team/${editingTeamMemberId}`, { method: "PUT", body: JSON.stringify(payload) });
    } else {
      await api("/research-team", { method: "POST", body: JSON.stringify(payload) });
    }
    closeModal("teamMemberModalBackdrop");
    await reloadResearchTeam();
  } catch (e) {
    $("teamMemberError").textContent = e.message;
  }
});

function openBlockEditModal(blockId) {
  if (blockId === "header") return openEditHeaderModal();
  if (LIST_BLOCK_SCHEMAS[blockId]) return openEditListModal(blockId);
}

function openEditHeaderModal() {
  const s = scientistData;
  $("editHeaderError").textContent = "";
  $("ehName").value = s.name || "";
  $("ehDesignation").value = s.designation || "";
  $("ehInstitute").value = s.institute || "";
  $("ehDob").value = s.dob || "";
  $("ehMobile").value = (s.mobile || []).join(", ");
  $("ehEmail").value = (s.email || []).join(", ");
  $("ehScholar").value = s.scholar_url || "";
  $("ehLinkedin").value = s.linkedin_url || "";
  $("ehPhoto").value = "";
  openModal("editHeaderModalBackdrop");
}

$("editHeaderSubmit").addEventListener("click", async () => {
  $("editHeaderError").textContent = "";
  try {
    if ($("ehPhoto").files[0]) {
      const fd = new FormData();
      fd.append("file", $("ehPhoto").files[0]);
      await apiUpload(`/scientist/photo?scientist_id=${currentScientistId}`, fd);
    }
    await api("/scientist", { method: "PUT", body: JSON.stringify({
      name: $("ehName").value, designation: $("ehDesignation").value, institute: $("ehInstitute").value,
      dob: $("ehDob").value,
      mobile: $("ehMobile").value.split(",").map(v => v.trim()).filter(Boolean),
      email: $("ehEmail").value.split(",").map(v => v.trim()).filter(Boolean),
      scholar_url: $("ehScholar").value, linkedin_url: $("ehLinkedin").value,
    }) });
    closeModal("editHeaderModalBackdrop");
    await loadProfile();
    await loadScientistSwitcher();
  } catch (e) {
    $("editHeaderError").textContent = e.message;
  }
});

let editingListBlockKey = null;
function openEditListModal(blockKey) {
  editingListBlockKey = blockKey;
  const schema = LIST_BLOCK_SCHEMAS[blockKey];
  $("editListTitle").textContent = schema.title;
  $("editListError").textContent = "";
  const data = scientistData[blockKey] || [];
  $("editListRows").innerHTML = "";
  data.forEach(item => addEditListRow(schema, item));
  if (data.length === 0) addEditListRow(schema, null);
  openModal("editListModalBackdrop");
}

function addEditListRow(schema, item) {
  const row = document.createElement("div");
  row.className = "edit-list-row";
  row.innerHTML = schema.fields.map(f => {
    const val = item ? (f.key === "_value" ? item : (item[f.key] || "")) : "";
    return `<input data-field="${f.key}" placeholder="${escapeHtml(f.label)}" value="${escapeHtml(val)}">`;
  }).join("") + `<button type="button" class="icon-btn danger edit-list-remove">Remove</button>`;
  row.querySelector(".edit-list-remove").addEventListener("click", () => row.remove());
  $("editListRows").appendChild(row);
}

$("editListAddRow").addEventListener("click", () => {
  addEditListRow(LIST_BLOCK_SCHEMAS[editingListBlockKey], null);
});

$("editListSubmit").addEventListener("click", async () => {
  $("editListError").textContent = "";
  const schema = LIST_BLOCK_SCHEMAS[editingListBlockKey];
  const rows = [...$("editListRows").querySelectorAll(".edit-list-row")];
  const values = rows.map(row => {
    const inputs = [...row.querySelectorAll("input")];
    if (schema.fields.length === 1 && schema.fields[0].key === "_value") {
      return inputs[0].value.trim();
    }
    const obj = {};
    inputs.forEach(inp => obj[inp.dataset.field] = inp.value.trim());
    return obj;
  }).filter(v => typeof v === "string" ? v : Object.values(v).some(x => x));

  try {
    await api("/scientist", { method: "PUT", body: JSON.stringify({ [editingListBlockKey]: values }) });
    closeModal("editListModalBackdrop");
    await loadProfile();
  } catch (e) {
    $("editListError").textContent = e.message;
  }
});

// ---------------- Add User ----------------
$("addUserBtn").addEventListener("click", () => {
  $("addUserError").textContent = "";
  $("newUserName").value = ""; $("newUserDesignation").value = ""; $("newUserInstitute").value = "";
  openModal("addUserModalBackdrop");
});

$("addUserSubmit").addEventListener("click", async () => {
  $("addUserError").textContent = "";
  try {
    const res = await api("/scientists", { method: "POST", body: JSON.stringify({
      name: $("newUserName").value, designation: $("newUserDesignation").value, institute: $("newUserInstitute").value,
    }) });
    closeModal("addUserModalBackdrop");
    currentScientistId = res.scientist_id;
    localStorage.setItem("currentScientistId", String(currentScientistId));
    await loadScientistSwitcher();
    await reloadForScientist();
    alert(res.message);
  } catch (e) {
    $("addUserError").textContent = e.message;
  }
});

// ---------------- Manage Login (super admin sets/resets a scientist's own login) ----------------
$("manageLoginBtn").addEventListener("click", () => {
  $("manageLoginError").textContent = ""; $("manageLoginSuccess").textContent = "";
  $("mlEmail").value = ""; $("mlPassword").value = "";
  const current = allScientists.find(s => s.scientist_id === currentScientistId);
  const name = current ? current.name : "this profile";
  $("manageLoginHint").textContent = `Set a login for ${name} so they can sign in and manage only their own content.`;
  if (current && current.login_email) $("mlEmail").value = current.login_email;
  openModal("manageLoginModalBackdrop");
});

$("manageLoginSubmit").addEventListener("click", async () => {
  $("manageLoginError").textContent = ""; $("manageLoginSuccess").textContent = "";
  try {
    const res = await api("/scientist/login", { method: "PUT", body: JSON.stringify({
      login_email: $("mlEmail").value, password: $("mlPassword").value,
    }) });
    $("manageLoginSuccess").textContent = res.message;
    await loadScientistSwitcher();
  } catch (e) {
    $("manageLoginError").textContent = e.message;
  }
});

$("manageLoginRemove").addEventListener("click", async () => {
  if (!confirm("Remove this profile's own login? Only the site admin will be able to manage it after this.")) return;
  $("manageLoginError").textContent = ""; $("manageLoginSuccess").textContent = "";
  try {
    const res = await api("/scientist/login", { method: "DELETE" });
    $("manageLoginSuccess").textContent = res.message;
    $("mlEmail").value = ""; $("mlPassword").value = "";
    await loadScientistSwitcher();
  } catch (e) {
    $("manageLoginError").textContent = e.message;
  }
});

// ---------------- Delete User ----------------
$("deleteUserBtn").addEventListener("click", async () => {
  const current = allScientists.find(s => s.scientist_id === currentScientistId);
  const name = current ? current.name : "this profile";
  if (!confirm(`Are you sure you want to delete ${name}? This permanently removes their entire profile — all publications, awards, projects, and every other record. This cannot be undone.`)) return;
  try {
    const res = await api(`/scientists/${currentScientistId}`, { method: "DELETE" });
    alert(res.message);
    await loadScientistSwitcher();
    currentScientistId = allScientists[0]?.scientist_id || 1;
    localStorage.setItem("currentScientistId", String(currentScientistId));
    await loadScientistSwitcher();
    await reloadForScientist();
  } catch (e) {
    alert(e.message);
  }
});

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
  if (section === "personal-details") { renderProfileBlocks("personalDetailsBlocks", PERSONAL_BLOCK_ORDER); return; }
  if (section === "book-chapters") { loadOtherPublications(); return; }
  if (section === "training") { loadTraining(); return; }
  const map = {
    "awards": { endpoint: "/awards", render: renderAwards, container: "awardsList" },
    "projects": { endpoint: "/projects", render: renderProjects, container: "projectsList" },
    "software": { endpoint: "/software", render: renderSoftware, container: "softwareList" },
    "courses-taught": { endpoint: "/courses-taught", render: renderCoursesTaught, container: "coursesTaughtList" },
    "students-guided": { endpoint: "/students-guided", render: renderStudentsGuided, container: "studentsGuidedList" },
    "technology": { endpoint: "/technology", render: renderTechnology, container: "technologyList" },
  };
  const cfg = map[section];
  if (!cfg) return;
  api(cfg.endpoint).then(items => cfg.render(items)).catch(() => {
    $(cfg.container).innerHTML = `<div class="empty-state">Could not load this section.</div>`;
  });
}

function loadOtherPublications() {
  const parts = [
    { endpoint: "/book-chapters", render: renderBookChapters, container: "bookChaptersList" },
    { endpoint: "/popular-articles", render: renderPopularArticles, container: "popularArticlesList" },
    { endpoint: "/policy-papers", render: renderPolicyPapers, container: "policyPapersList" },
    { endpoint: "/manuals", render: renderManuals, container: "manualsList" },
  ];
  parts.forEach(cfg => {
    api(cfg.endpoint).then(items => cfg.render(items)).catch(() => {
      $(cfg.container).innerHTML = `<div class="empty-state">Could not load this section.</div>`;
    });
  });
}

function loadTraining() {
  const parts = [
    { endpoint: "/conference-papers", render: renderConferencePapers, container: "conferencePapersList" },
    { endpoint: "/trainings-attended", render: renderTrainingsAttended, container: "trainingsAttendedList" },
    { endpoint: "/trainings-organised", render: renderTrainingsOrganised, container: "trainingsOrganisedList" },
    { endpoint: "/invited-talks", render: renderInvitedTalks, container: "invitedTalksList" },
  ];
  parts.forEach(cfg => {
    api(cfg.endpoint).then(items => cfg.render(items)).catch(() => {
      $(cfg.container).innerHTML = `<div class="empty-state">Could not load this section.</div>`;
    });
  });
}

document.querySelectorAll('#otherPubSubtabs .pub-subtab').forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll('#otherPubSubtabs .pub-subtab').forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    const key = tab.dataset.otherPub;
    document.querySelectorAll('.other-pub-panel').forEach(panel => {
      panel.classList.toggle("hidden", panel.dataset.otherPubPanel !== key);
    });
  });
});

document.querySelectorAll('#trainingSubtabs .pub-subtab').forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll('#trainingSubtabs .pub-subtab').forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    const key = tab.dataset.trainingSub;
    document.querySelectorAll('[data-training-panel]').forEach(panel => {
      panel.classList.toggle("hidden", panel.dataset.trainingPanel !== key);
    });
  });
});

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
          <label class="cv-tick" title="Include in CV">
            <input type="checkbox" data-paper-cv="${p.publication_id}" ${p.cv_included ? "checked" : ""}>
          </label>
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
  list.querySelectorAll("[data-paper-cv]").forEach(b => b.addEventListener("change", () => togglePaperCvIncluded(b.dataset.paperCv)));
  setupSelectAllTick("publications", papers, "publication_id", id => `/papers/${id}/toggle-cv-included`, () => loadPapers());
}

async function togglePaperCvIncluded(id) {
  try {
    await api(`/papers/${id}/toggle-cv-included`, { method: "POST" });
    await loadPapers();
  } catch (e) {
    alert(e.message);
  }
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
function openLoginModal(entryPoint) {
  loginEntryPoint = entryPoint;
  $("loginModalTitle").textContent = entryPoint === "user" ? "User Login" : "Admin Login";
  $("loginModalHint").textContent = entryPoint === "user"
    ? "Sign in with the email and password given to you by the site admin to manage your own profile."
    : "Sign in to manage the whole site.";
  $("loginStep1").classList.remove("hidden");
  $("loginStep2").classList.add("hidden");
  $("loginError").textContent = "";
  $("loginEmail").value = ""; $("loginPassword").value = "";
  openModal("loginModalBackdrop");
}

function signOut() {
  authToken = null;
  sessionRole = null;
  sessionScientistId = null;
  loginEntryPoint = null;
  onAuthChange();
}

$("adminBtn").addEventListener("click", () => {
  if (authToken) { signOut(); return; }
  openLoginModal("admin");
});

$("userLoginBtn").addEventListener("click", () => {
  if (authToken) { signOut(); return; }
  openLoginModal("user");
});

$("loginSubmit").addEventListener("click", async () => {
  $("loginError").textContent = "";
  try {
    const res = await api("/login", {
      method: "POST",
      body: JSON.stringify({ email: $("loginEmail").value, password: $("loginPassword").value, login_type: loginEntryPoint }),
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
    sessionRole = res.role || "super_admin";
    sessionScientistId = res.scientist_id || null;
    closeModal("loginModalBackdrop");
    if (sessionRole === "scientist" && sessionScientistId) {
      currentScientistId = sessionScientistId;
      localStorage.setItem("currentScientistId", String(currentScientistId));
      await loadScientistSwitcher();
      await reloadForScientist();
    }
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
  const isSuperAdmin = visible && sessionRole !== "scientist";

  // Show only whichever login button was used; the other stays hidden while
  // logged in, and the active one becomes "Sign out" for that session.
  if (visible) {
    $("adminBtn").classList.toggle("hidden", loginEntryPoint !== "admin");
    $("userLoginBtn").classList.toggle("hidden", loginEntryPoint !== "user");
    $("adminBtn").textContent = "Sign out";
    $("userLoginBtn").textContent = "Sign out";
  } else {
    $("adminBtn").classList.remove("hidden");
    $("userLoginBtn").classList.remove("hidden");
    $("adminBtn").textContent = "Admin";
    $("userLoginBtn").textContent = "User Login";
  }

  // Available to any logged-in profile owner (or the super admin)
  $("addPublicationBtn").classList.toggle("hidden", !visible);
  $("enrichAllBtn").classList.toggle("hidden", !visible);
  $("updateDownloadsBtn").classList.toggle("hidden", !visible);
  $("downloadCvBtn").classList.toggle("hidden", !visible);
  document.querySelectorAll(".add-record-btn").forEach(b => b.classList.toggle("hidden", !visible));
  document.querySelectorAll(".section-header-tick").forEach(b => b.classList.toggle("hidden", !visible));

  // Super-admin only — site-wide tools that touch more than one profile's data
  $("exportBackupBtn").classList.toggle("hidden", !isSuperAdmin);
  $("exportSnapshotBtn").classList.toggle("hidden", !isSuperAdmin);
  $("resetScoresBtn").classList.toggle("hidden", !isSuperAdmin);
  $("uploadNaasBtn").classList.toggle("hidden", !isSuperAdmin);
  $("uploadJcrBtn").classList.toggle("hidden", !isSuperAdmin);
  $("addUserBtn").classList.toggle("hidden", !isSuperAdmin);
  $("manageLoginBtn").classList.toggle("hidden", !isSuperAdmin);
  $("deleteUserBtn").classList.toggle("hidden", !isSuperAdmin);

  // A scientist's own login can only ever view/edit their own profile —
  // lock the switcher so they can't even try to select someone else's.
  $("scientistSwitcher").disabled = (sessionRole === "scientist");

  // re-render profile blocks so admin controls (drag handles, hide buttons) appear/disappear
  renderProfileBlocks("profileBlocks", HOME_BLOCK_ORDER);
  renderProfileBlocks("personalDetailsBlocks", PERSONAL_BLOCK_ORDER);
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

$("updateDownloadsBtn").addEventListener("click", async () => {
  if (!confirm("Fetch the current all-time download count for every R package from CRAN's live download logs? This can take up to a minute.")) return;
  $("updateDownloadsBtn").textContent = "Updating...";
  $("updateDownloadsBtn").disabled = true;
  try {
    const res = await api("/software/update-downloads", { method: "POST" });
    alert(res.message);
    loadSection("software");
  } catch (e) {
    alert(e.message);
  } finally {
    $("updateDownloadsBtn").textContent = "\u21BB Update Download Counts";
    $("updateDownloadsBtn").disabled = false;
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

// ---------------- CV download (direct — uses whatever is currently ticked across the site) ----------------
$("downloadCvBtn").addEventListener("click", async () => {
  const btn = $("downloadCvBtn");
  const originalText = btn.textContent;
  btn.textContent = "Generating...";
  btn.disabled = true;
  try {
    const headers = {};
    if (authToken) headers["Authorization"] = "Bearer " + authToken;
    const res = await fetch(API_BASE + `/cv/download?scientist_id=${currentScientistId}`, { method: "GET", headers });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || "Could not generate the CV.");
    }
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    const cd = res.headers.get("Content-Disposition") || "";
    const nameMatch = cd.match(/filename="?([^"]+)"?/);
    a.href = url; a.download = nameMatch ? nameMatch[1] : "CV.pdf";
    document.body.appendChild(a); a.click(); a.remove();
    window.URL.revokeObjectURL(url);
  } catch (e) {
    alert(e.message);
  } finally {
    btn.textContent = originalText;
    btn.disabled = false;
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
      { key: "investigators", label: "Investigators", full: true },
      { key: "project_title", label: "Project Title", full: true },
      { key: "funding_agency", label: "Funding Agency" },
      { key: "date_start", label: "Start Date" },
      { key: "date_end", label: "End Date" },
      { key: "status", label: "Status" },
    ],
  },
  "book-chapters": {
    idField: "book_chapter_id",
    label: "Book Chapter",
    fields: [
      { key: "title", label: "Chapter Title", full: true },
      { key: "authors", label: "Authors", full: true },
      { key: "editor", label: "Editor" },
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
  "courses-taught": {
    idField: "course_id",
    label: "Course Taught",
    fields: [
      { key: "course_name", label: "Course", full: true },
    ],
  },
  "students-guided": {
    idField: "student_id",
    label: "Student",
    fields: [
      { key: "name", label: "Name" },
      { key: "student_type", label: "Student Type", options: ["PhD", "M.Sc.", "B.Sc.", "Post-Doc", "Other"] },
      { key: "start_date", label: "Start Date" },
      { key: "end_date", label: "End Date" },
      { key: "description", label: "Description", full: true },
    ],
  },
  "technology": {
    idField: "tech_id",
    label: "Technology / Patent",
    fields: [
      { key: "category", label: "Category", options: ["Patent", "Technology", "Copyright"] },
      { key: "authors", label: "Authors", full: true },
      { key: "year", label: "Year" },
      { key: "id_number", label: "Patent / Accession No." },
      { key: "title", label: "Title", full: true },
    ],
  },
  "popular-articles": {
    idField: "article_id",
    label: "Popular Article",
    fields: [
      { key: "authors", label: "Authors", full: true },
      { key: "year", label: "Year" },
      { key: "publication", label: "Publication" },
      { key: "title", label: "Title", full: true },
      { key: "details", label: "Volume / Pages", full: true },
    ],
  },
  "policy-papers": {
    idField: "paper_id",
    label: "Policy Paper",
    fields: [
      { key: "authors", label: "Authors", full: true },
      { key: "year", label: "Year" },
      { key: "id_number", label: "Reference No." },
      { key: "title", label: "Title", full: true },
      { key: "publisher", label: "Publisher", full: true },
    ],
  },
  "manuals": {
    idField: "manual_id",
    label: "Manual",
    fields: [
      { key: "authors", label: "Authors", full: true },
      { key: "year", label: "Year" },
      { key: "title", label: "Title", full: true },
      { key: "publisher", label: "Publisher", full: true },
    ],
  },
  "conference-papers": {
    idField: "paper_id",
    label: "Conference Paper",
    fields: [
      { key: "authors", label: "Authors", full: true },
      { key: "year", label: "Year" },
      { key: "title", label: "Title", full: true },
      { key: "details", label: "Conference / Event Details", full: true },
    ],
  },
  "trainings-attended": {
    idField: "entry_id",
    label: "Training/Conference Attended",
    fields: [
      { key: "year", label: "Year" },
      { key: "description", label: "Description", full: true },
    ],
  },
  "trainings-organised": {
    idField: "entry_id",
    label: "Training/Conference Organised",
    fields: [
      { key: "year", label: "Year" },
      { key: "description", label: "Description", full: true },
    ],
  },
  "invited-talks": {
    idField: "talk_id",
    label: "Invited Talk",
    fields: [
      { key: "year", label: "Year" },
      { key: "description", label: "Description", full: true },
    ],
  },
};

function recordTagsHtml(item) {
  return item.hidden ? `<span class="tag tag-hidden">Hidden</span>` : "";
}

function recordActionsHtml(type, id, hidden, cvIncluded) {
  return `
    <div class="record-actions admin-actions ${authToken ? "visible" : ""}">
      <label class="cv-tick" title="Include in CV">
        <input type="checkbox" data-record-cv="${type}" data-id="${id}" ${cvIncluded ? "checked" : ""}>
      </label>
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
      ${recordActionsHtml("awards", it.award_id, it.hidden, it.cv_included)}
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
        <div class="record-meta">${escapeHtml(it.funding_agency)} &middot; Started ${escapeHtml(it.date_start)}${it.date_end ? " &middot; Ended " + escapeHtml(it.date_end) : ""} &middot; ${escapeHtml(it.status)} ${recordTagsHtml(it)}</div>
      </div>
      ${recordActionsHtml("projects", it.project_id, it.hidden, it.cv_included)}
    </div>
  `).join("") : `<div class="empty-state">No projects yet.</div>`;
  wireRecordButtons("projects", items, "project_id");
}

function renderBookChapters(items) {
  $("bookChaptersList").innerHTML = items.length ? items.map(it => `
    <div class="record-entry" data-id="${it.book_chapter_id}">
      <div class="record-main">
        <h3 class="record-title">${escapeHtml(it.title)}</h3>
        <div class="record-meta">${escapeHtml(it.authors)}${it.editor ? " &middot; Editor: " + escapeHtml(it.editor) : ""}</div>
        <div class="record-meta">${escapeHtml(it.book_title)}${it.publisher ? ", " + escapeHtml(it.publisher) : ""} &middot; ${escapeHtml(it.year)}${it.pages ? " &middot; pp. " + escapeHtml(it.pages) : ""}${it.doi ? ` &middot; <a href="${it.doi.startsWith("http") ? it.doi : "https://doi.org/" + it.doi}" target="_blank" rel="noopener">${escapeHtml(it.doi)}</a>` : ""} ${recordTagsHtml(it)}</div>
      </div>
      ${recordActionsHtml("book-chapters", it.book_chapter_id, it.hidden, it.cv_included)}
    </div>
  `).join("") : `<div class="empty-state">No book chapters added yet.</div>`;
  wireRecordButtons("book-chapters", items, "book_chapter_id");
}

function renderPopularArticles(items) {
  $("popularArticlesList").innerHTML = items.length ? items.map(it => `
    <div class="record-entry" data-id="${it.article_id}">
      <div class="record-main">
        <h3 class="record-title">${escapeHtml(it.title)}</h3>
        <div class="record-meta">${escapeHtml(it.authors)}</div>
        <div class="record-meta">${escapeHtml(it.publication)}${it.details ? ", " + escapeHtml(it.details) : ""}${it.year ? " &middot; " + escapeHtml(it.year) : ""} ${recordTagsHtml(it)}</div>
      </div>
      ${recordActionsHtml("popular-articles", it.article_id, it.hidden, it.cv_included)}
    </div>
  `).join("") : `<div class="empty-state">No popular articles added yet.</div>`;
  wireRecordButtons("popular-articles", items, "article_id");
}

function renderPolicyPapers(items) {
  $("policyPapersList").innerHTML = items.length ? items.map(it => `
    <div class="record-entry" data-id="${it.paper_id}">
      <div class="record-main">
        <h3 class="record-title">${escapeHtml(it.title)}</h3>
        <div class="record-meta">${escapeHtml(it.authors)}</div>
        <div class="record-meta">${escapeHtml(it.publisher)}${it.year ? " &middot; " + escapeHtml(it.year) : ""}${it.id_number ? " &middot; " + escapeHtml(it.id_number) : ""} ${recordTagsHtml(it)}</div>
      </div>
      ${recordActionsHtml("policy-papers", it.paper_id, it.hidden, it.cv_included)}
    </div>
  `).join("") : `<div class="empty-state">No policy papers added yet.</div>`;
  wireRecordButtons("policy-papers", items, "paper_id");
}

function renderManuals(items) {
  $("manualsList").innerHTML = items.length ? items.map(it => `
    <div class="record-entry" data-id="${it.manual_id}">
      <div class="record-main">
        <h3 class="record-title">${escapeHtml(it.title)}</h3>
        <div class="record-meta">${escapeHtml(it.authors)}</div>
        <div class="record-meta">${escapeHtml(it.publisher)}${it.year ? " &middot; " + escapeHtml(it.year) : ""} ${recordTagsHtml(it)}</div>
      </div>
      ${recordActionsHtml("manuals", it.manual_id, it.hidden, it.cv_included)}
    </div>
  `).join("") : `<div class="empty-state">No manuals added yet.</div>`;
  wireRecordButtons("manuals", items, "manual_id");
}

function renderConferencePapers(items) {
  $("conferencePapersList").innerHTML = items.length ? items.map(it => `
    <div class="record-entry" data-id="${it.paper_id}">
      <div class="record-main">
        <h3 class="record-title">${escapeHtml(it.title)}</h3>
        <div class="record-meta">${escapeHtml(it.authors)}${it.year ? " &middot; " + escapeHtml(it.year) : ""}</div>
        <div class="record-meta">${escapeHtml(it.details)} ${recordTagsHtml(it)}</div>
      </div>
      ${recordActionsHtml("conference-papers", it.paper_id, it.hidden, it.cv_included)}
    </div>
  `).join("") : `<div class="empty-state">No conference papers added yet.</div>`;
  wireRecordButtons("conference-papers", items, "paper_id");
}

function renderTrainingsAttended(items) {
  $("trainingsAttendedList").innerHTML = items.length ? items.map(it => `
    <div class="record-entry" data-id="${it.entry_id}">
      <div class="record-main">
        <div class="record-meta">${it.year ? "<strong>" + escapeHtml(it.year) + "</strong> &middot; " : ""}${escapeHtml(it.description)} ${recordTagsHtml(it)}</div>
      </div>
      ${recordActionsHtml("trainings-attended", it.entry_id, it.hidden, it.cv_included)}
    </div>
  `).join("") : `<div class="empty-state">No trainings/conferences attended added yet.</div>`;
  wireRecordButtons("trainings-attended", items, "entry_id");
}

function renderTrainingsOrganised(items) {
  $("trainingsOrganisedList").innerHTML = items.length ? items.map(it => `
    <div class="record-entry" data-id="${it.entry_id}">
      <div class="record-main">
        <div class="record-meta">${it.year ? "<strong>" + escapeHtml(it.year) + "</strong> &middot; " : ""}${escapeHtml(it.description)} ${recordTagsHtml(it)}</div>
      </div>
      ${recordActionsHtml("trainings-organised", it.entry_id, it.hidden, it.cv_included)}
    </div>
  `).join("") : `<div class="empty-state">No trainings/conferences organised added yet.</div>`;
  wireRecordButtons("trainings-organised", items, "entry_id");
}

function renderInvitedTalks(items) {
  $("invitedTalksList").innerHTML = items.length ? items.map(it => `
    <div class="record-entry" data-id="${it.talk_id}">
      <div class="record-main">
        <div class="record-meta">${it.year ? "<strong>" + escapeHtml(it.year) + "</strong> &middot; " : ""}${escapeHtml(it.description)} ${recordTagsHtml(it)}</div>
      </div>
      ${recordActionsHtml("invited-talks", it.talk_id, it.hidden, it.cv_included)}
    </div>
  `).join("") : `<div class="empty-state">No invited talks added yet.</div>`;
  wireRecordButtons("invited-talks", items, "talk_id");
}

function renderSoftware(items) {
  $("softwareList").innerHTML = items.length ? items.map(it => `
    <div class="record-entry" data-id="${it.software_id}">
      <div class="record-main">
        <h3 class="record-title">${escapeHtml(it.package_name)}</h3>
        <div class="record-meta">${escapeHtml(it.reference)}</div>
        <div class="record-meta">${escapeHtml(it.year)}${it.downloads ? " &middot; " + escapeHtml(it.downloads) + " downloads" : ""}${it.cran_url ? ` &middot; <a href="${escapeHtml(it.cran_url)}" target="_blank" rel="noopener">CRAN</a>` : ""} ${recordTagsHtml(it)}</div>
      </div>
      ${recordActionsHtml("software", it.software_id, it.hidden, it.cv_included)}
    </div>
  `).join("") : `<div class="empty-state">No software packages yet.</div>`;
  wireRecordButtons("software", items, "software_id");
}

function renderCoursesTaught(items) {
  $("coursesTaughtList").innerHTML = items.length ? items.map(it => `
    <div class="record-entry" data-id="${it.course_id}">
      <div class="record-main">
        <h3 class="record-title">${escapeHtml(it.course_name)}</h3>
        <div class="record-meta">${recordTagsHtml(it)}</div>
      </div>
      ${recordActionsHtml("courses-taught", it.course_id, it.hidden, it.cv_included)}
    </div>
  `).join("") : `<div class="empty-state">No courses added yet.</div>`;
  wireRecordButtons("courses-taught", items, "course_id");
}

function renderStudentsGuided(items) {
  $("studentsGuidedList").innerHTML = items.length ? items.map(it => `
    <div class="record-entry" data-id="${it.student_id}">
      <div class="record-main">
        <h3 class="record-title">${escapeHtml(it.name)}${it.student_type ? ` <span class="tag tag-domain">${escapeHtml(it.student_type)}</span>` : ""}</h3>
        <div class="record-meta">${it.start_date ? escapeHtml(it.start_date) : ""}${it.end_date ? " &ndash; " + escapeHtml(it.end_date) : ""}</div>
        <div class="record-meta">${escapeHtml(it.description || "")} ${recordTagsHtml(it)}</div>
      </div>
      ${recordActionsHtml("students-guided", it.student_id, it.hidden, it.cv_included)}
    </div>
  `).join("") : `<div class="empty-state">No students added yet.</div>`;
  wireRecordButtons("students-guided", items, "student_id");
}

function renderTechnology(items) {
  const patents = items.filter(it => it.category === "Patent");
  const tech = items.filter(it => it.category === "Technology");
  const copyrights = items.filter(it => it.category === "Copyright");

  const idLabel = (category) => category === "Patent" ? "Patent No." : category === "Copyright" ? "Copyright No." : "Accession No.";

  const renderGroup = (title, groupItems) => {
    if (!groupItems.length) return "";
    const rows = groupItems.map(it => `
      <div class="record-entry" data-id="${it.tech_id}">
        <div class="record-main">
          <h3 class="record-title">${escapeHtml(it.title)}</h3>
          <div class="record-meta">${escapeHtml(it.authors)}</div>
          <div class="record-meta">${escapeHtml(it.year)} &middot; ${idLabel(it.category)} ${escapeHtml(it.id_number)} ${recordTagsHtml(it)}</div>
        </div>
        ${recordActionsHtml("technology", it.tech_id, it.hidden, it.cv_included)}
      </div>
    `).join("");
    return `<h3 class="tech-group-title">${title}</h3>${rows}`;
  };

  const html = renderGroup("Design Patent", patents) + renderGroup("Technology", tech) + renderGroup("Copyright", copyrights);
  $("technologyList").innerHTML = html || `<div class="empty-state">No technology, patents, or copyrights added yet.</div>`;
  wireRecordButtons("technology", items, "tech_id");
}

async function setupSelectAllTick(sectionKey, items, idField, endpointFn, reloadFn) {
  const tick = document.querySelector(`.section-header-tick[data-select-all="${sectionKey}"]`);
  if (!tick) return;
  const checkbox = tick.querySelector("input");
  const allIncluded = items.length > 0 && items.every(it => !!it.cv_included);
  checkbox.checked = allIncluded;
  checkbox.onchange = async () => {
    const newState = checkbox.checked;
    const toToggle = items.filter(it => !!it.cv_included !== newState);
    checkbox.disabled = true;
    try {
      for (const it of toToggle) {
        await api(endpointFn(it[idField]), { method: "POST" });
      }
      await reloadFn();
    } catch (e) {
      alert(e.message);
    } finally {
      checkbox.disabled = false;
    }
  };
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
  document.querySelectorAll(`[data-record-cv="${type}"]`).forEach(b => {
    b.addEventListener("change", () => toggleRecordCvIncluded(type, b.dataset.id));
  });
  setupSelectAllTick(type, items, idField, id => `/${type}/${id}/toggle-cv-included`, () => loadSection(type));
}

async function toggleRecordCvIncluded(type, id) {
  try {
    await api(`/${type}/${id}/toggle-cv-included`, { method: "POST" });
    loadSection(type);
  } catch (e) {
    alert(e.message);
  }
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
      ${f.options
        ? `<select id="r_${f.key}">${f.options.map(o => `<option value="${escapeHtml(o)}" ${record && record[f.key] === o ? "selected" : ""}>${escapeHtml(o)}</option>`).join("")}</select>`
        : `<input id="r_${f.key}" value="${escapeHtml(record ? record[f.key] : "")}">`}
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

// ---------------- scientist switcher ----------------
async function loadScientistSwitcher() {
  try {
    allScientists = await api("/scientists");
  } catch (e) {
    allScientists = [];
    return;
  }
  const sel = $("scientistSwitcher");
  if (!allScientists.some(s => s.scientist_id === currentScientistId)) {
    currentScientistId = allScientists[0]?.scientist_id || 1;
  }
  sel.innerHTML = allScientists.map(s =>
    `<option value="${s.scientist_id}" ${s.scientist_id === currentScientistId ? "selected" : ""}>${escapeHtml(s.name)}</option>`
  ).join("");
}

$("scientistSwitcher").addEventListener("change", async (e) => {
  currentScientistId = parseInt(e.target.value, 10);
  localStorage.setItem("currentScientistId", String(currentScientistId));
  await reloadForScientist();
});

async function reloadForScientist() {
  await loadProfile();
  await loadFilterOptions();
  await loadStats();
  if (currentSection === "publications") {
    await loadPapers();
  } else {
    loadSection(currentSection);
  }
}

// ---------------- init ----------------
(async function init() {
  await loadScientistSwitcher();
  await loadProfile();
  await loadFilterOptions();
  await loadStats();
  await loadPapers();
})();
