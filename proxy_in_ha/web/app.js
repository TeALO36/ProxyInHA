/**
 * ProxyInHA — Dashboard Application
 * Handles CRUD operations for proxy services, health checks, and UI interactions.
 */

(function () {
    "use strict";

    // ── Configuration ────────────────────────────────────────────────
    // Detect the ingress base path from the current URL
    const INGRESS_BASE = detectIngressBase();
    const API_BASE = INGRESS_BASE + "api";
    const PROXY_BASE = INGRESS_BASE + "proxy";
    const HEALTH_POLL_INTERVAL = 30000; // 30s

    function detectIngressBase() {
        const path = window.location.pathname;
        // Match HA ingress pattern: /api/hassio_ingress/<token>/
        const match = path.match(/^(\/api\/hassio_ingress\/[^/]+\/)/);
        if (match) return match[1];
        // Fallback to root
        return "/";
    }

    // ── DOM References ───────────────────────────────────────────────
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    const dom = {
        statsCount: $("#stats-count"),
        btnRefresh: $("#btn-refresh"),
        btnReloadNginx: $("#btn-reload-nginx"),
        toggleAddForm: $("#toggle-add-form"),
        chevronAdd: $("#chevron-add"),
        addForm: $("#add-service-form"),
        loadingState: $("#loading-state"),
        emptyState: $("#empty-state"),
        servicesGrid: $("#services-grid"),
        editModal: $("#edit-modal"),
        editForm: $("#edit-service-form"),
        editId: $("#edit-id"),
        editName: $("#edit-name"),
        editUrl: $("#edit-url"),
        editIcon: $("#edit-icon"),
        editEnabled: $("#edit-enabled"),
        btnCloseModal: $("#btn-close-modal"),
        btnCancelEdit: $("#btn-cancel-edit"),
        toastContainer: $("#toast-container"),
    };

    // ── State ────────────────────────────────────────────────────────
    let services = [];
    let healthData = {};
    let healthTimer = null;

    // ── API Helpers ──────────────────────────────────────────────────
    async function api(method, path, body) {
        const opts = {
            method,
            headers: { "Content-Type": "application/json" },
        };
        if (body) opts.body = JSON.stringify(body);
        const res = await fetch(API_BASE + path, opts);
        return res.json();
    }

    // ── Toast Notifications ──────────────────────────────────────────
    function toast(message, type = "info") {
        const icons = {
            success: "mdi-check-circle",
            error: "mdi-alert-circle",
            info: "mdi-information",
        };
        const el = document.createElement("div");
        el.className = `toast ${type}`;
        el.innerHTML = `<span class="mdi ${icons[type] || icons.info}"></span><span>${message}</span>`;
        dom.toastContainer.appendChild(el);
        setTimeout(() => {
            el.style.animation = "toastIn 0.3s ease reverse forwards";
            setTimeout(() => el.remove(), 300);
        }, 3500);
    }

    // ── Slugify ──────────────────────────────────────────────────────
    function slugify(name) {
        return name
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, "-")
            .replace(/^-|-$/g, "");
    }

    // ── Render Services ──────────────────────────────────────────────
    function renderServices() {
        dom.loadingState.classList.add("hidden");

        if (services.length === 0) {
            dom.emptyState.classList.remove("hidden");
            dom.servicesGrid.classList.add("hidden");
            dom.statsCount.textContent = "0 services";
            return;
        }

        dom.emptyState.classList.add("hidden");
        dom.servicesGrid.classList.remove("hidden");
        dom.statsCount.textContent = `${services.length} service${services.length > 1 ? "s" : ""}`;

        dom.servicesGrid.innerHTML = services
            .map((svc, i) => {
                const health = healthData[svc.id] || {};
                const statusClass = health.status || "checking";
                const statusLabel =
                    statusClass === "online"
                        ? "En ligne"
                        : statusClass === "offline"
                        ? "Hors ligne"
                        : "Vérification...";
                const slug = slugify(svc.name);
                const iconClass = (svc.icon || "mdi:server-network").replace("mdi:", "mdi-");
                const disabledClass = svc.enabled ? "" : "disabled";

                return `
                <div class="service-card ${disabledClass}" style="animation-delay: ${i * 60}ms" data-id="${svc.id}">
                    <div class="card-header">
                        <div class="card-title-group">
                            <div class="card-icon">
                                <span class="mdi ${iconClass}"></span>
                            </div>
                            <div>
                                <div class="card-title">${escapeHtml(svc.name)}</div>
                                <div class="card-url">${escapeHtml(svc.url)}</div>
                            </div>
                        </div>
                        <div class="status-badge ${statusClass}">
                            <span class="status-dot"></span>
                            ${statusLabel}
                        </div>
                    </div>
                    <div class="card-actions">
                        <button class="btn btn-sm btn-open" onclick="window.open('${PROXY_BASE}/${slug}/', '_blank')" title="Ouvrir dans un nouvel onglet">
                            <span class="mdi mdi-open-in-new"></span> Ouvrir
                        </button>
                        <button class="btn btn-sm btn-edit" onclick="ProxyApp.editService('${svc.id}')" title="Modifier">
                            <span class="mdi mdi-pencil"></span> Modifier
                        </button>
                        <button class="btn btn-sm btn-delete" onclick="ProxyApp.deleteService('${svc.id}')" title="Supprimer">
                            <span class="mdi mdi-delete"></span>
                        </button>
                    </div>
                </div>`;
            })
            .join("");
    }

    function escapeHtml(str) {
        const div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    // ── Load Services ────────────────────────────────────────────────
    async function loadServices() {
        try {
            services = await api("GET", "/services");
            renderServices();
            checkAllHealth();
        } catch (err) {
            toast("Erreur de chargement des services", "error");
            dom.loadingState.classList.add("hidden");
            dom.emptyState.classList.remove("hidden");
        }
    }

    // ── Health Checks ────────────────────────────────────────────────
    async function checkAllHealth() {
        try {
            const results = await api("GET", "/health");
            if (Array.isArray(results)) {
                results.forEach((r) => {
                    healthData[r.id] = r;
                });
                renderServices();
            }
        } catch (err) {
            // Silently fail health checks
        }
    }

    function startHealthPolling() {
        if (healthTimer) clearInterval(healthTimer);
        healthTimer = setInterval(checkAllHealth, HEALTH_POLL_INTERVAL);
    }

    // ── Add Service ──────────────────────────────────────────────────
    async function addService(e) {
        e.preventDefault();
        const name = $("#svc-name").value.trim();
        const url = $("#svc-url").value.trim();
        const icon = $("#svc-icon").value.trim() || "mdi:server-network";
        const enabled = $("#svc-enabled").checked;

        if (!name || !url) {
            toast("Nom et URL sont requis", "error");
            return;
        }

        try {
            const result = await api("POST", "/services", { name, url, icon, enabled });
            if (result.error) {
                toast(result.error, "error");
                return;
            }
            toast(`Service "${name}" ajouté !`, "success");
            dom.addForm.reset();
            $("#svc-icon").value = "mdi:server-network";
            $("#svc-enabled").checked = true;
            await loadServices();
        } catch (err) {
            toast("Erreur lors de l'ajout", "error");
        }
    }

    // ── Edit Service ─────────────────────────────────────────────────
    function openEditModal(id) {
        const svc = services.find((s) => s.id === id);
        if (!svc) return;

        dom.editId.value = svc.id;
        dom.editName.value = svc.name;
        dom.editUrl.value = svc.url;
        dom.editIcon.value = svc.icon || "mdi:server-network";
        dom.editEnabled.checked = svc.enabled;
        dom.editModal.classList.remove("hidden");
    }

    function closeEditModal() {
        dom.editModal.classList.add("hidden");
    }

    async function saveEdit(e) {
        e.preventDefault();
        const id = dom.editId.value;
        const data = {
            name: dom.editName.value.trim(),
            url: dom.editUrl.value.trim(),
            icon: dom.editIcon.value.trim(),
            enabled: dom.editEnabled.checked,
        };

        try {
            const result = await api("PUT", `/services/${id}`, data);
            if (result.error) {
                toast(result.error, "error");
                return;
            }
            toast(`Service "${data.name}" mis à jour !`, "success");
            closeEditModal();
            await loadServices();
        } catch (err) {
            toast("Erreur lors de la modification", "error");
        }
    }

    // ── Delete Service ───────────────────────────────────────────────
    async function deleteService(id) {
        const svc = services.find((s) => s.id === id);
        if (!svc) return;
        if (!confirm(`Supprimer le service "${svc.name}" ?`)) return;

        try {
            const result = await api("DELETE", `/services/${id}`);
            if (result.error) {
                toast(result.error, "error");
                return;
            }
            toast(`Service "${svc.name}" supprimé`, "success");
            await loadServices();
        } catch (err) {
            toast("Erreur lors de la suppression", "error");
        }
    }

    // ── Reload Nginx ─────────────────────────────────────────────────
    async function reloadNginx() {
        dom.btnReloadNginx.classList.add("spinning");
        try {
            const result = await api("POST", "/reload");
            if (result.success) {
                toast("Nginx rechargé avec succès !", "success");
            } else {
                toast("Erreur Nginx : " + result.message, "error");
            }
        } catch (err) {
            toast("Erreur de communication avec l'API", "error");
        }
        setTimeout(() => dom.btnReloadNginx.classList.remove("spinning"), 1000);
    }

    // ── Toggle Add Form ──────────────────────────────────────────────
    function toggleAddForm() {
        dom.addForm.classList.toggle("collapsed");
        dom.chevronAdd.classList.toggle("rotated");
    }

    // ── Event Listeners ──────────────────────────────────────────────
    dom.addForm.addEventListener("submit", addService);
    dom.editForm.addEventListener("submit", saveEdit);
    dom.toggleAddForm.addEventListener("click", toggleAddForm);
    dom.btnRefresh.addEventListener("click", () => {
        dom.btnRefresh.classList.add("spinning");
        loadServices().then(() => {
            setTimeout(() => dom.btnRefresh.classList.remove("spinning"), 600);
        });
    });
    dom.btnReloadNginx.addEventListener("click", reloadNginx);
    dom.btnCloseModal.addEventListener("click", closeEditModal);
    dom.btnCancelEdit.addEventListener("click", closeEditModal);
    dom.editModal.addEventListener("click", (e) => {
        if (e.target === dom.editModal) closeEditModal();
    });

    // ── Public API (for inline onclick handlers) ─────────────────────
    window.ProxyApp = {
        editService: openEditModal,
        deleteService: deleteService,
    };

    // ── Init ─────────────────────────────────────────────────────────
    loadServices();
    startHealthPolling();
})();
