/**
 * ProxyInHA v1.1.0 — Dashboard App
 * CRUD services + mTLS public exposure option
 */
(function () {
    "use strict";

    const API_BASE = "./api";
    const HEALTH_POLL = 30000;

    const $ = id => document.getElementById(id);
    const dom = {
        statsCount:     $("stats-count"),
        certStatus:     $("cert-status"),
        certDomain:     $("cert-domain"),
        alertNoCerts:   $("alert-no-certs"),
        btnRefresh:     $("btn-refresh"),
        btnReloadNginx: $("btn-reload-nginx"),
        toggleAddForm:  $("toggle-add-form"),
        chevronAdd:     $("chevron-add"),
        addForm:        $("add-service-form"),
        loadingState:   $("loading-state"),
        emptyState:     $("empty-state"),
        servicesGrid:   $("services-grid"),
        editModal:      $("edit-modal"),
        editForm:       $("edit-service-form"),
        editId:         $("edit-id"),
        editName:       $("edit-name"),
        editUrl:        $("edit-url"),
        editIcon:       $("edit-icon"),
        editEnabled:    $("edit-enabled"),
        editPublic:     $("edit-public"),
        editPublicPort: $("edit-public-port"),
        mtlsPortEdit:   $("mtls-port-edit"),
        btnCloseModal:  $("btn-close-modal"),
        btnCancelEdit:  $("btn-cancel-edit"),
        toastContainer: $("toast-container"),
        // Add form mTLS
        svcPublic:      $("svc-public"),
        mtlsPortAdd:    $("mtls-port-add"),
        svcPublicPort:  $("svc-public-port"),
    };

    let services = [];
    let healthData = {};
    let healthTimer = null;

    // ── API ─────────────────────────────────────────────────────────
    async function api(method, path, body) {
        const opts = { method, headers: { "Content-Type": "application/json" } };
        if (body) opts.body = JSON.stringify(body);
        const res = await fetch(API_BASE + path, opts);
        return res.json();
    }

    // ── Toast ────────────────────────────────────────────────────────
    function toast(msg, type = "info") {
        const icons = { success: "mdi-check-circle", error: "mdi-alert-circle", info: "mdi-information" };
        const el = document.createElement("div");
        el.className = `toast ${type}`;
        el.innerHTML = `<span class="mdi ${icons[type]}"></span><span>${msg}</span>`;
        dom.toastContainer.appendChild(el);
        setTimeout(() => { el.style.animation = "toastIn .3s ease reverse"; setTimeout(() => el.remove(), 300); }, 3500);
    }

    function slugify(name) {
        return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    }

    function esc(str) {
        const d = document.createElement("div");
        d.textContent = str;
        return d.innerHTML;
    }

    // ── Info / Certs ─────────────────────────────────────────────────
    async function loadInfo() {
        try {
            const info = await api("GET", "/info");
            if (info.certs && info.certs.server_cert && info.certs.ca_cert) {
                dom.certStatus.classList.remove("hidden");
                dom.certDomain.textContent = info.domain || "mTLS OK";
                dom.alertNoCerts.classList.add("hidden");
            } else {
                dom.certStatus.classList.add("hidden");
                dom.alertNoCerts.classList.remove("hidden");
            }
        } catch (_) {}
    }

    // ── Render ───────────────────────────────────────────────────────
    function renderServices() {
        dom.loadingState.classList.add("hidden");

        if (!services.length) {
            dom.emptyState.classList.remove("hidden");
            dom.servicesGrid.classList.add("hidden");
            dom.statsCount.textContent = "0 services";
            return;
        }

        dom.emptyState.classList.add("hidden");
        dom.servicesGrid.classList.remove("hidden");
        dom.statsCount.textContent = `${services.length} service${services.length > 1 ? "s" : ""}`;

        dom.servicesGrid.innerHTML = services.map((svc, i) => {
            const health = healthData[svc.id] || {};
            const statusClass = health.status || "checking";
            const statusLabel = { online: "En ligne", offline: "Hors ligne", checking: "Vérification..." }[statusClass] || "Vérification...";
            const slug = slugify(svc.name);
            const iconClass = (svc.icon || "mdi:server-network").replace("mdi:", "mdi-");
            const isPublic = svc.public && svc.public_port;
            const mtlsCardClass = isPublic ? "mtls-card" : "";
            const disabledClass = svc.enabled ? "" : "disabled";

            const mtlsBadge = isPublic
                ? `<div class="mtls-badge"><span class="mdi mdi-shield-lock"></span>:${svc.public_port}</div>`
                : "";

            const openMtlsBtn = isPublic
                ? `<button class="btn btn-sm btn-open-mtls" onclick="ProxyApp.openMtls('${esc(svc.id)}')" title="Ouvrir via mTLS (port ${svc.public_port})"><span class="mdi mdi-shield-lock"></span> :${svc.public_port}</button>`
                : "";

            return `
            <div class="service-card ${mtlsCardClass} ${disabledClass}" style="animation-delay:${i * 60}ms" data-id="${svc.id}">
                <div class="card-header">
                    <div class="card-title-group">
                        <div class="card-icon"><span class="mdi ${iconClass}"></span></div>
                        <div>
                            <div class="card-title">${esc(svc.name)}</div>
                            <div class="card-url">${esc(svc.url)}</div>
                        </div>
                    </div>
                    <div class="card-badges">
                        <div class="status-badge ${statusClass}">
                            <span class="status-dot"></span>${statusLabel}
                        </div>
                        ${mtlsBadge}
                    </div>
                </div>
                <div class="card-actions">
                    <button class="btn btn-sm btn-open" onclick="window.open('./proxy/${slug}/', '_blank')">
                        <span class="mdi mdi-open-in-new"></span> Ouvrir
                    </button>
                    ${openMtlsBtn}
                    <button class="btn btn-sm btn-edit" onclick="ProxyApp.editService('${svc.id}')">
                        <span class="mdi mdi-pencil"></span>
                    </button>
                    <button class="btn btn-sm btn-delete" onclick="ProxyApp.deleteService('${svc.id}')">
                        <span class="mdi mdi-delete"></span>
                    </button>
                </div>
            </div>`;
        }).join("");
    }

    // ── Load ─────────────────────────────────────────────────────────
    async function loadServices() {
        try {
            services = await api("GET", "/services");
            renderServices();
            pollHealth();
        } catch (_) {
            toast("Erreur de chargement", "error");
            dom.loadingState.classList.add("hidden");
            dom.emptyState.classList.remove("hidden");
        }
    }

    // ── Health ───────────────────────────────────────────────────────
    async function pollHealth() {
        try {
            const results = await api("GET", "/health");
            if (Array.isArray(results)) {
                results.forEach(r => { healthData[r.id] = r; });
                renderServices();
            }
        } catch (_) {}
    }

    function startHealthPolling() {
        if (healthTimer) clearInterval(healthTimer);
        healthTimer = setInterval(pollHealth, HEALTH_POLL);
    }

    // ── Add ──────────────────────────────────────────────────────────
    async function addService(e) {
        e.preventDefault();
        const data = {
            name:        $("svc-name").value.trim(),
            url:         $("svc-url").value.trim(),
            icon:        $("svc-icon").value.trim() || "mdi:server-network",
            enabled:     $("svc-enabled").checked,
            public:      dom.svcPublic.checked,
            public_port: dom.svcPublic.checked ? parseInt(dom.svcPublicPort.value) || null : null,
        };
        if (!data.name || !data.url) { toast("Nom et URL requis", "error"); return; }

        const result = await api("POST", "/services", data);
        if (result.error) { toast(result.error, "error"); return; }
        toast(`Service "${data.name}" ajouté !`, "success");
        dom.addForm.reset();
        $("svc-icon").value = "mdi:server-network";
        dom.mtlsPortAdd.classList.add("hidden");
        await loadServices();
    }

    // ── Edit ─────────────────────────────────────────────────────────
    function openEdit(id) {
        const svc = services.find(s => s.id === id);
        if (!svc) return;
        dom.editId.value = svc.id;
        dom.editName.value = svc.name;
        dom.editUrl.value = svc.url;
        dom.editIcon.value = svc.icon || "mdi:server-network";
        dom.editEnabled.checked = svc.enabled;
        dom.editPublic.checked = svc.public || false;
        dom.editPublicPort.value = svc.public_port || "";
        dom.mtlsPortEdit.classList.toggle("hidden", !svc.public);
        dom.editModal.classList.remove("hidden");
    }

    function closeEdit() { dom.editModal.classList.add("hidden"); }

    async function saveEdit(e) {
        e.preventDefault();
        const id = dom.editId.value;
        const data = {
            name:        dom.editName.value.trim(),
            url:         dom.editUrl.value.trim(),
            icon:        dom.editIcon.value.trim(),
            enabled:     dom.editEnabled.checked,
            public:      dom.editPublic.checked,
            public_port: dom.editPublic.checked ? parseInt(dom.editPublicPort.value) || null : null,
        };
        const result = await api("PUT", `/services/${id}`, data);
        if (result.error) { toast(result.error, "error"); return; }
        toast(`Service "${data.name}" mis à jour !`, "success");
        closeEdit();
        await loadServices();
    }

    // ── Delete ───────────────────────────────────────────────────────
    async function deleteService(id) {
        const svc = services.find(s => s.id === id);
        if (!svc || !confirm(`Supprimer "${svc.name}" ?`)) return;
        const result = await api("DELETE", `/services/${id}`);
        if (result.error) { toast(result.error, "error"); return; }
        toast(`"${svc.name}" supprimé`, "success");
        await loadServices();
    }

    // ── Open mTLS ────────────────────────────────────────────────────
    function openMtls(id) {
        const svc = services.find(s => s.id === id);
        if (!svc || !svc.public_port) return;
        const url = new URL(window.location.href);
        window.open(`https://${url.hostname}:${svc.public_port}/`, "_blank");
    }

    // ── Reload Nginx ─────────────────────────────────────────────────
    async function reloadNginx() {
        dom.btnReloadNginx.classList.add("spinning");
        const result = await api("POST", "/reload");
        toast(result.success ? "Nginx rechargé ✓" : "Erreur : " + result.message, result.success ? "success" : "error");
        setTimeout(() => dom.btnReloadNginx.classList.remove("spinning"), 800);
    }

    // ── Events ───────────────────────────────────────────────────────
    dom.addForm.addEventListener("submit", addService);
    dom.editForm.addEventListener("submit", saveEdit);
    dom.toggleAddForm.addEventListener("click", () => {
        dom.addForm.classList.toggle("collapsed");
        dom.chevronAdd.classList.toggle("rotated");
    });
    dom.btnRefresh.addEventListener("click", () => {
        dom.btnRefresh.classList.add("spinning");
        Promise.all([loadServices(), loadInfo()]).then(() =>
            setTimeout(() => dom.btnRefresh.classList.remove("spinning"), 600));
    });
    dom.btnReloadNginx.addEventListener("click", reloadNginx);
    dom.btnCloseModal.addEventListener("click", closeEdit);
    dom.btnCancelEdit.addEventListener("click", closeEdit);
    dom.editModal.addEventListener("click", e => { if (e.target === dom.editModal) closeEdit(); });

    // mTLS toggle — add form
    dom.svcPublic.addEventListener("change", () => {
        dom.mtlsPortAdd.classList.toggle("hidden", !dom.svcPublic.checked);
    });
    // mTLS toggle — edit form
    dom.editPublic.addEventListener("change", () => {
        dom.mtlsPortEdit.classList.toggle("hidden", !dom.editPublic.checked);
    });

    // ── Public API for inline onclick ────────────────────────────────
    window.ProxyApp = { editService: openEdit, deleteService, openMtls };

    // ── Init ─────────────────────────────────────────────────────────
    loadInfo();
    loadServices();
    startHealthPolling();
})();
