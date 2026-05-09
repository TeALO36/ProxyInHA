/* ProxyInHA v1.3.0 — App Logic */
(function () {
    "use strict";
    const API = "./api";
    const $ = id => document.getElementById(id);

    const dom = {
        statsCount: $("stats-count"), certPill: $("cert-pill"), certPillTxt: $("cert-pill-text"),
        btnRefresh: $("btn-refresh"), btnReloadNginx: $("btn-reload-nginx"),
        toggleCerts: $("toggle-certs"), chevronCerts: $("chevron-certs"), certsPanel: $("certs-panel"),
        certIndServer: $("cert-ind-server"), certIndCa: $("cert-ind-ca"), certIndClient: $("cert-ind-client"),
        certsModeInfo: $("certs-mode-info"), btnRegenCerts: $("btn-regen-certs"),
        btnDlClient: $("btn-dl-client"), btnDlCa: $("btn-dl-ca"),
        toggleAdd: $("toggle-add-form"), chevronAdd: $("chevron-add"), addForm: $("add-service-form"),
        loading: $("loading-state"), empty: $("empty-state"), grid: $("services-grid"),
        editModal: $("edit-modal"), editForm: $("edit-service-form"),
        editId: $("edit-id"), editName: $("edit-name"), editUrl: $("edit-url"),
        editIcon: $("edit-icon"), editEnabled: $("edit-enabled"),
        editPublic: $("edit-public"), editPublicPort: $("edit-public-port"),
        mtlsPortEdit: $("mtls-port-edit"), btnCloseModal: $("btn-close-modal"), btnCancelEdit: $("btn-cancel-edit"),
        svcPublic: $("svc-public"), mtlsPortAdd: $("mtls-port-add"), svcPublicPort: $("svc-public-port"),
        toasts: $("toast-container"),
    };

    let services = [], healthData = {}, healthTimer = null;

    // ── API ─────────────────────────────────────────────────────────
    async function api(method, path, body) {
        const opts = { method, headers: { "Content-Type": "application/json" } };
        if (body) opts.body = JSON.stringify(body);
        const r = await fetch(API + path, opts);
        return r.json();
    }

    // ── Toast ────────────────────────────────────────────────────────
    function toast(msg, type = "info") {
        const icons = { success: "mdi-check-circle", error: "mdi-alert-circle", info: "mdi-information" };
        const el = document.createElement("div");
        el.className = `toast ${type}`;
        el.innerHTML = `<span class="mdi ${icons[type]}"></span><span>${msg}</span>`;
        dom.toasts.appendChild(el);
        setTimeout(() => { el.style.animation = "toastIn .3s ease reverse"; setTimeout(() => el.remove(), 300); }, 4000);
    }

    function slugify(n) { return n.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""); }
    function esc(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }

    // ── Cert status ──────────────────────────────────────────────────
    function setCertIndicator(el, ok) {
        el.className = `cert-indicator ${ok ? "ok" : "fail"}`;
        el.innerHTML = `<span class="mdi ${ok ? "mdi-check-circle" : "mdi-close-circle"}"></span>`;
    }

    async function loadCerts() {
        try {
            const c = await api("GET", "/certs");
            setCertIndicator(dom.certIndServer, c.server_cert);
            setCertIndicator(dom.certIndCa,     c.ca_cert);
            setCertIndicator(dom.certIndClient,  c.client_p12);

            const modeLabels = { auto: "🔧 Auto-généré (CA interne)", caddy: "🔗 Caddy (Let's Encrypt)", custom: "📁 Personnalisé" };
            dom.certsModeInfo.textContent = `Mode : ${modeLabels[c.tls_mode] || c.tls_mode}${c.domain ? ` · Domaine : ${c.domain}` : ""}`;

            if (c.server_cert && c.ca_cert) {
                dom.certPill.classList.remove("hidden");
                dom.certPillTxt.textContent = c.domain ? `TLS · ${c.domain}` : "TLS OK";
            } else {
                dom.certPill.classList.add("hidden");
            }
        } catch (_) {}
    }

    // ── Render services ──────────────────────────────────────────────
    function render() {
        dom.loading.classList.add("hidden");
        dom.statsCount.textContent = `${services.length} service${services.length > 1 ? "s" : ""}`;

        if (!services.length) {
            dom.empty.classList.remove("hidden");
            dom.grid.classList.add("hidden");
            return;
        }
        dom.empty.classList.add("hidden");
        dom.grid.classList.remove("hidden");

        dom.grid.innerHTML = services.map((svc, i) => {
            const h = healthData[svc.id] || {};
            const sc = h.status || "checking";
            const slabel = { online: "En ligne", offline: "Hors ligne", checking: "Vérification..." }[sc];
            const slug = slugify(svc.name);
            const icon = (svc.icon || "mdi:server-network").replace("mdi:", "mdi-");
            const isMtls = svc.public && svc.public_port;

            return `<div class="service-card ${isMtls ? "mtls-card" : ""} ${svc.enabled ? "" : "disabled"}" style="animation-delay:${i*60}ms">
                <div class="card-header">
                    <div class="card-title-group">
                        <div class="card-icon"><span class="mdi ${icon}"></span></div>
                        <div><div class="card-title">${esc(svc.name)}</div><div class="card-url">${esc(svc.url)}</div></div>
                    </div>
                    <div class="card-badges">
                        <div class="status-badge ${sc}"><span class="status-dot"></span>${slabel}</div>
                        ${isMtls ? `<div class="mtls-badge"><span class="mdi mdi-shield-lock"></span>:${svc.public_port}</div>` : ""}
                    </div>
                </div>
                <div class="card-actions">
                    <button class="btn btn-sm btn-open" onclick="ProxyApp.openProxy('${slug}')"><span class="mdi mdi-open-in-new"></span> Ouvrir</button>
                    ${isMtls ? `<button class="btn btn-sm btn-open-mtls" onclick="ProxyApp.openMtls('${svc.id}')"><span class="mdi mdi-shield-lock"></span>:${svc.public_port}</button>` : ""}
                    <button class="btn btn-sm btn-edit" onclick="ProxyApp.editService('${svc.id}')"><span class="mdi mdi-pencil"></span></button>
                    <button class="btn btn-sm btn-delete" onclick="ProxyApp.deleteService('${svc.id}')"><span class="mdi mdi-delete"></span></button>
                </div>
            </div>`;
        }).join("");
    }

    async function load() {
        try { services = await api("GET", "/services"); render(); poll(); }
        catch (_) { toast("Erreur chargement", "error"); dom.loading.classList.add("hidden"); dom.empty.classList.remove("hidden"); }
    }

    async function poll() {
        try {
            const r = await api("GET", "/health");
            if (Array.isArray(r)) { r.forEach(x => { healthData[x.id] = x; }); render(); }
        } catch (_) {}
    }

    function startPoll() { if (healthTimer) clearInterval(healthTimer); healthTimer = setInterval(poll, 30000); }

    // ── Add ──────────────────────────────────────────────────────────
    async function addService(e) {
        e.preventDefault();
        const data = {
            name: $("svc-name").value.trim(), url: $("svc-url").value.trim(),
            icon: $("svc-icon").value.trim() || "mdi:server-network",
            enabled: $("svc-enabled").checked, public: dom.svcPublic.checked,
            public_port: dom.svcPublic.checked ? parseInt(dom.svcPublicPort.value) || null : null,
        };
        if (!data.name || !data.url) { toast("Nom et URL requis", "error"); return; }
        const r = await api("POST", "/services", data);
        if (r.error) { toast(r.error, "error"); return; }
        toast(`"${data.name}" ajouté !`, "success");
        dom.addForm.reset(); $("svc-icon").value = "mdi:server-network";
        dom.mtlsPortAdd.classList.add("hidden");
        await load();
    }

    // ── Edit ─────────────────────────────────────────────────────────
    function openEdit(id) {
        const s = services.find(x => x.id === id); if (!s) return;
        dom.editId.value = s.id; dom.editName.value = s.name; dom.editUrl.value = s.url;
        dom.editIcon.value = s.icon || "mdi:server-network"; dom.editEnabled.checked = s.enabled;
        dom.editPublic.checked = s.public || false; dom.editPublicPort.value = s.public_port || "";
        dom.mtlsPortEdit.classList.toggle("hidden", !s.public);
        dom.editModal.classList.remove("hidden");
    }
    function closeEdit() { dom.editModal.classList.add("hidden"); }

    async function saveEdit(e) {
        e.preventDefault();
        const data = {
            name: dom.editName.value.trim(), url: dom.editUrl.value.trim(),
            icon: dom.editIcon.value.trim(), enabled: dom.editEnabled.checked,
            public: dom.editPublic.checked,
            public_port: dom.editPublic.checked ? parseInt(dom.editPublicPort.value) || null : null,
        };
        const r = await api("PUT", `/services/${dom.editId.value}`, data);
        if (r.error) { toast(r.error, "error"); return; }
        toast(`"${data.name}" mis à jour !`, "success"); closeEdit(); await load();
    }

    // ── Delete ───────────────────────────────────────────────────────
    async function del(id) {
        const s = services.find(x => x.id === id);
        if (!s || !confirm(`Supprimer "${s.name}" ?`)) return;
        const r = await api("DELETE", `/services/${id}`);
        if (r.error) { toast(r.error, "error"); return; }
        toast(`"${s.name}" supprimé`, "success"); await load();
    }

    function openMtls(id) {
        const s = services.find(x => x.id === id);
        if (!s?.public_port) return;
        window.open(`https://${location.hostname}:${s.public_port}/`, "_blank");
    }

    // ── Cert actions ─────────────────────────────────────────────────
    async function regenCerts() {
        dom.btnRegenCerts.disabled = true;
        dom.btnRegenCerts.innerHTML = '<span class="mdi mdi-loading" style="animation:spin 1s linear infinite"></span> Génération en cours…';
        toast("Génération des certificats…", "info");
        try {
            const r = await api("POST", "/certs/regenerate");
            toast(r.success ? "Certificats générés ✓" : `Erreur : ${r.message}`, r.success ? "success" : "error");
            await loadCerts();
        } catch (_) { toast("Erreur de génération", "error"); }
        dom.btnRegenCerts.disabled = false;
        dom.btnRegenCerts.innerHTML = '<span class="mdi mdi-autorenew"></span> Générer / Regénérer les certificats';
    }

    function downloadFile(path, filename) {
        const a = document.createElement("a");
        a.href = API + path; a.download = filename; a.click();
    }

    // ── Events ───────────────────────────────────────────────────────
    dom.addForm.addEventListener("submit", addService);
    dom.editForm.addEventListener("submit", saveEdit);
    dom.toggleAdd.addEventListener("click", () => { dom.addForm.classList.toggle("collapsed"); dom.chevronAdd.classList.toggle("rotated"); });
    dom.toggleCerts.addEventListener("click", () => { dom.certsPanel.classList.toggle("collapsed"); dom.chevronCerts.classList.toggle("rotated"); });
    dom.btnRefresh.addEventListener("click", () => { dom.btnRefresh.classList.add("spinning"); Promise.all([load(), loadCerts()]).then(() => setTimeout(() => dom.btnRefresh.classList.remove("spinning"), 600)); });
    dom.btnReloadNginx.addEventListener("click", async () => { dom.btnReloadNginx.classList.add("spinning"); const r = await api("POST", "/reload"); toast(r.success ? "Nginx rechargé ✓" : `Erreur: ${r.message}`, r.success ? "success" : "error"); setTimeout(() => dom.btnReloadNginx.classList.remove("spinning"), 800); });
    dom.btnCloseModal.addEventListener("click", closeEdit);
    dom.btnCancelEdit.addEventListener("click", closeEdit);
    dom.editModal.addEventListener("click", e => { if (e.target === dom.editModal) closeEdit(); });
    dom.svcPublic.addEventListener("change", () => dom.mtlsPortAdd.classList.toggle("hidden", !dom.svcPublic.checked));
    dom.editPublic.addEventListener("change", () => dom.mtlsPortEdit.classList.toggle("hidden", !dom.editPublic.checked));
    dom.btnRegenCerts.addEventListener("click", regenCerts);
    dom.btnDlClient.addEventListener("click", () => downloadFile("/certs/download/client", "proxyinha-client.p12"));
    dom.btnDlCa.addEventListener("click", () => downloadFile("/certs/download/ca", "proxyinha-ca.crt"));

    function openProxy(slug) {
        // Obtenir l'URL de base absolue correcte. 
        // Si on est dans l'ingress HA, location.href = .../api/hassio_ingress/TOKEN/
        const href = window.location.href;
        const base = href.substring(0, href.lastIndexOf('/') + 1) || href + '/';
        const url = base + 'proxy/' + slug + '/';
        window.open(url, '_blank');
    }

    window.ProxyApp = { editService: openEdit, deleteService: del, openMtls, openProxy };


    // ── HA Theme Sync ────────────────────────────────────────────────
    function syncHaTheme() {
        try {
            const parentDoc = window.parent && window.parent.document;
            if (!parentDoc || parentDoc === document) return;

            const parentStyles = getComputedStyle(parentDoc.documentElement);
            const root = document.documentElement.style;

            // Map HA CSS variables → our --ha-* intermediaries
            const map = {
                '--ha-bg':            '--primary-background-color',
                '--ha-bg-secondary':  '--secondary-background-color',
                '--ha-bg-card':       '--card-background-color',
                '--ha-bg-card-hover': '--card-background-color',
                '--ha-text':          '--primary-text-color',
                '--ha-text-secondary':'--secondary-text-color',
                '--ha-text-muted':    '--disabled-text-color',
                '--ha-border':        '--divider-color',
                '--ha-accent':        '--primary-color',
                '--ha-accent-hover':  '--primary-color',
                '--ha-border-focus':  '--primary-color',
                '--ha-font':          '--paper-font-body1_-_font-family',
            };

            let applied = 0;
            for (const [our, ha] of Object.entries(map)) {
                const val = parentStyles.getPropertyValue(ha).trim();
                if (val) {
                    root.setProperty(our, val);
                    applied++;
                }
            }

            // Derive glow/overlay from accent
            const accent = parentStyles.getPropertyValue('--primary-color').trim();
            if (accent) {
                root.setProperty('--ha-accent-glow', accent.replace(')', ', 0.25)').replace('rgb(', 'rgba('));
                root.setProperty('--ha-overlay', 'rgba(0,0,0,0.5)');
            }

            if (applied > 0) {
                console.log(`[ProxyInHA] HA theme synced (${applied} variables)`);
            }
        } catch (e) {
            // Cross-origin or no parent — use fallback theme
            console.log('[ProxyInHA] Standalone mode (no HA theme)');
        }
    }

    // ── Init ─────────────────────────────────────────────────────────
    syncHaTheme();
    // Re-sync theme periodically in case user changes it
    setInterval(syncHaTheme, 5000);

    loadCerts();
    load();
    startPoll();
    // Ouvrir automatiquement le panneau certs au 1er chargement
    setTimeout(() => { dom.certsPanel.classList.remove("collapsed"); dom.chevronCerts.classList.add("rotated"); }, 300);
})();
