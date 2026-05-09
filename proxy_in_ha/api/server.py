"""ProxyInHA v1.2.4 — Flask serves everything: static files + API"""

import json, os, re, subprocess, uuid, urllib.request, urllib.error
from flask import Flask, jsonify, request, send_file, send_from_directory

# Flask sert les fichiers statiques depuis /var/www/html
app = Flask(__name__, static_folder="/var/www/html", static_url_path="")

SERVICES_DB    = os.environ.get("SERVICES_DB",    "/data/services.json")
NGINX_CONF_DIR = os.environ.get("NGINX_CONF_DIR", "/etc/nginx/conf.d")
MTLS_CONF_DIR  = os.environ.get("MTLS_CONF_DIR",  "/etc/nginx/mtls.d")
NGINX_CERTS    = os.environ.get("NGINX_CERTS",    "/etc/nginx/certs")
DATA_CERTS     = os.environ.get("DATA_CERTS",     "/data/certs")
DOMAIN         = os.environ.get("DOMAIN",         "")
TLS_MODE       = os.environ.get("TLS_MODE",       "auto")

# ── Helpers ──────────────────────────────────────────────────────────────────
def load_services():
    try:
        with open(SERVICES_DB) as f:
            svcs = json.load(f)
        for s in svcs:
            if "id" not in s:
                s["id"] = str(uuid.uuid4())[:8]
        return svcs
    except Exception:
        return []

def save_services(svcs):
    os.makedirs(os.path.dirname(SERVICES_DB), exist_ok=True)
    with open(SERVICES_DB, "w") as f:
        json.dump(svcs, f, indent=2)

def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

def run_cmd(*args):
    r = subprocess.run(list(args), capture_output=True, text=True)
    return r.returncode == 0, r.stdout + r.stderr

def reload_nginx():
    ok, _ = run_cmd("nginx", "-t")
    if not ok:
        return False, "Config nginx invalide"
    ok, msg = run_cmd("nginx", "-s", "reload")
    return ok, msg or "Nginx rechargé"

def generate_internal_conf(svcs):
    os.makedirs(NGINX_CONF_DIR, exist_ok=True)
    # Supprimer les anciens fichiers proxy_*
    for f in os.listdir(NGINX_CONF_DIR):
        if f.startswith("proxy_") and f.endswith(".conf"):
            os.remove(os.path.join(NGINX_CONF_DIR, f))

    for svc in svcs:
        if not svc.get("enabled"):
            continue
        slug = slugify(svc["name"])
        url  = svc["url"].rstrip("/")
        conf_path = os.path.join(NGINX_CONF_DIR, f"proxy_{slug}.conf")
        with open(conf_path, "w") as f:
            f.write(f"""# Proxy interne pour {svc['name']}
location /proxy/{slug}/ {{
    proxy_pass {url}/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $http_host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Accept-Encoding "";
    proxy_buffering off;
    proxy_read_timeout 86400s;
    proxy_send_timeout 86400s;

    # Reecrire les chemins absolus dans les reponses HTML
    sub_filter 'src="/assets/'  'src="/proxy/{slug}/assets/';
    sub_filter 'href="/assets/' 'href="/proxy/{slug}/assets/';
    sub_filter 'src="/static/'  'src="/proxy/{slug}/static/';
    sub_filter 'href="/static/' 'href="/proxy/{slug}/static/';
    sub_filter 'src="/js/'      'src="/proxy/{slug}/js/';
    sub_filter 'href="/css/'    'href="/proxy/{slug}/css/';
    sub_filter_once off;
    sub_filter_types text/html;
}}

# Assets de {svc['name']} (chemins absolus des SPAs)
location /proxy/{slug}/assets/ {{
    proxy_pass {url}/assets/;
    proxy_http_version 1.1;
    proxy_set_header Host $http_host;
    proxy_buffering off;
    proxy_read_timeout 30s;
}}
location /proxy/{slug}/static/ {{
    proxy_pass {url}/static/;
    proxy_http_version 1.1;
    proxy_set_header Host $http_host;
    proxy_buffering off;
}}
location /proxy/{slug}/js/ {{
    proxy_pass {url}/js/;
    proxy_http_version 1.1;
    proxy_set_header Host $http_host;
    proxy_buffering off;
}}
location /proxy/{slug}/css/ {{
    proxy_pass {url}/css/;
    proxy_http_version 1.1;
    proxy_set_header Host $http_host;
    proxy_buffering off;
}}
""")






def generate_mtls_conf(svcs):
    os.makedirs(MTLS_CONF_DIR, exist_ok=True)
    for f in os.listdir(MTLS_CONF_DIR):
        if f.endswith(".conf"):
            os.remove(os.path.join(MTLS_CONF_DIR, f))

    server_crt = os.path.join(NGINX_CERTS, "server.crt")
    server_key = os.path.join(NGINX_CERTS, "server.key")
    ca_crt     = os.path.join(NGINX_CERTS, "ca.crt")
    if not os.path.exists(server_crt) or not os.path.exists(server_key):
        return

    ca_block = f"\n    ssl_client_certificate {ca_crt};\n    ssl_verify_client on;" if os.path.exists(ca_crt) else ""
    sn = DOMAIN or "_"

    for svc in svcs:
        if not (svc.get("enabled") and svc.get("public") and svc.get("public_port")):
            continue
        slug = slugify(svc["name"])
        url  = svc["url"].rstrip("/")
        port = svc["public_port"]
        with open(os.path.join(MTLS_CONF_DIR, f"mtls_{slug}.conf"), "w") as f:
            f.write(f"""server {{
    listen {port} ssl;
    server_name {sn};
    ssl_certificate     {server_crt};
    ssl_certificate_key {server_key};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL_{slug}:10m;{ca_block}

    location / {{
        proxy_pass {url}/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Client-Cert-DN $ssl_client_s_dn;
        proxy_set_header X-Client-Verified $ssl_client_verify;
        proxy_buffering off;
        proxy_read_timeout 86400s;
    }}
}}\n""")

def apply_all(svcs):
    generate_internal_conf(svcs)
    generate_mtls_conf(svcs)
    return reload_nginx()

def check_health(url, timeout=5):
    try:
        # Pour HTTPS locaux, ne pas vérifier le cert
        ctx = None
        if url.startswith("https://"):
            import ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        resp = urllib.request.urlopen(
            urllib.request.Request(url), timeout=timeout, context=ctx
        )
        return {"status": "online", "code": resp.getcode()}
    except urllib.error.HTTPError as e:
        return {"status": "online" if e.code in (401, 403, 302) else "error", "code": e.code}
    except Exception:
        return {"status": "offline", "code": None}

def cert_status():
    return {
        "server_cert": os.path.exists(os.path.join(NGINX_CERTS, "server.crt")),
        "server_key":  os.path.exists(os.path.join(NGINX_CERTS, "server.key")),
        "ca_cert":     os.path.exists(os.path.join(NGINX_CERTS, "ca.crt")),
        "client_p12":  os.path.exists(os.path.join(DATA_CERTS, "client.p12")),
        "tls_mode":    TLS_MODE,
        "domain":      DOMAIN,
    }

def regen_certs():
    domain = DOMAIN or "proxyinha.local"
    d = DATA_CERTS
    os.makedirs(d, exist_ok=True)
    ext = f"[v3_req]\nsubjectAltName = @alt_names\n[alt_names]\nDNS.1 = {domain}\nDNS.2 = localhost\nIP.1 = 127.0.0.1\n"
    with open("/tmp/server_ext.cnf", "w") as f:
        f.write(ext)
    cmds = [
        ["openssl", "genrsa", "-out", f"{d}/ca.key", "4096"],
        ["openssl", "req", "-new", "-x509", "-days", "3650", "-key", f"{d}/ca.key",
         "-out", f"{d}/ca.crt", "-subj", "/C=FR/O=ProxyInHA/CN=ProxyInHA Root CA"],
        ["openssl", "genrsa", "-out", f"{d}/server.key", "2048"],
        ["openssl", "req", "-new", "-key", f"{d}/server.key", "-out", f"{d}/server.csr",
         "-subj", f"/C=FR/O=ProxyInHA/CN={domain}"],
        ["openssl", "x509", "-req", "-days", "825", "-in", f"{d}/server.csr",
         "-CA", f"{d}/ca.crt", "-CAkey", f"{d}/ca.key", "-CAcreateserial",
         "-out", f"{d}/server.crt", "-extfile", "/tmp/server_ext.cnf", "-extensions", "v3_req"],
        ["openssl", "genrsa", "-out", f"{d}/client.key", "2048"],
        ["openssl", "req", "-new", "-key", f"{d}/client.key", "-out", f"{d}/client.csr",
         "-subj", "/C=FR/O=ProxyInHA/CN=ProxyInHA Client"],
        ["openssl", "x509", "-req", "-days", "825", "-in", f"{d}/client.csr",
         "-CA", f"{d}/ca.crt", "-CAkey", f"{d}/ca.key", "-CAcreateserial",
         "-out", f"{d}/client.crt"],
        ["openssl", "pkcs12", "-export", "-in", f"{d}/client.crt",
         "-inkey", f"{d}/client.key", "-certfile", f"{d}/ca.crt",
         "-out", f"{d}/client.p12", "-passout", "pass:proxyinha"],
    ]
    for cmd in cmds:
        ok, err = run_cmd(*cmd)
        if not ok:
            return False, f"Erreur {cmd[2]}: {err}"
    import shutil
    shutil.copy(f"{d}/server.crt", os.path.join(NGINX_CERTS, "server.crt"))
    shutil.copy(f"{d}/server.key", os.path.join(NGINX_CERTS, "server.key"))
    shutil.copy(f"{d}/ca.crt",    os.path.join(NGINX_CERTS, "ca.crt"))
    os.chmod(os.path.join(NGINX_CERTS, "server.key"), 0o600)
    return True, "Certificats régénérés"

# ── Routes statiques ──────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("/var/www/html", "index.html")

@app.route("/<path:path>")
def static_files(path):
    # Ne pas intercepter les routes /api/
    if path.startswith("api/") or path.startswith("proxy/"):
        return jsonify({"error": "Not found"}), 404
    try:
        return send_from_directory("/var/www/html", path)
    except Exception:
        return send_from_directory("/var/www/html", "index.html")

# ── Proxy interne vers les services ──────────────────────────────────────────
@app.route("/proxy/<slug>/", defaults={"subpath": ""})
@app.route("/proxy/<slug>/<path:subpath>")
def proxy_service(slug, subpath):
    """Proxy HTTP transparent vers le service local."""
    svcs = load_services()
    svc  = next((s for s in svcs if slugify(s["name"]) == slug and s.get("enabled")), None)
    if not svc:
        return jsonify({"error": f"Service '{slug}' introuvable"}), 404

    target_url = svc["url"].rstrip("/") + "/" + subpath
    if request.query_string:
        target_url += "?" + request.query_string.decode()

    try:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        headers = dict(request.headers)
        headers.pop("Host", None)
        req = urllib.request.Request(
            target_url,
            data=request.get_data() or None,
            headers={k: v for k, v in headers.items() if k.lower() not in ("content-length",)},
            method=request.method,
        )
        resp = urllib.request.urlopen(req, timeout=30, context=ctx)
        content = resp.read()
        from flask import Response
        return Response(
            content,
            status=resp.getcode(),
            headers={k: v for k, v in resp.headers.items()
                     if k.lower() not in ("transfer-encoding", "connection")},
        )
    except urllib.error.HTTPError as e:
        from flask import Response
        return Response(e.read(), status=e.code, headers=dict(e.headers))
    except Exception as ex:
        return jsonify({"error": str(ex)}), 502

# ── API ───────────────────────────────────────────────────────────────────────
@app.route("/api/info")
def api_info():
    svcs = load_services()
    return jsonify({
        "version": "1.2.4",
        "domain": DOMAIN, "tls_mode": TLS_MODE,
        "total_services": len(svcs),
        "enabled_services": sum(1 for s in svcs if s.get("enabled")),
        "public_services":  sum(1 for s in svcs if s.get("public") and s.get("enabled")),
        "certs": cert_status(),
    })

@app.route("/api/services")
def list_services():
    return jsonify(load_services())

@app.route("/api/services", methods=["POST"])
def add_service():
    data = request.get_json()
    if not data or not data.get("name") or not data.get("url"):
        return jsonify({"error": "name et url requis"}), 400
    svcs = load_services()
    if any(s["name"].lower() == data["name"].lower() for s in svcs):
        return jsonify({"error": f"'{data['name']}' existe déjà"}), 409
    svc = {
        "id": str(uuid.uuid4())[:8],
        "name": data["name"],
        "url":  data["url"].rstrip("/"),
        "icon": data.get("icon", "mdi:server-network"),
        "enabled":     data.get("enabled", True),
        "public":      data.get("public", False),
        "public_port": data.get("public_port") or None,
    }
    svcs.append(svc)
    save_services(svcs)
    ok, msg = apply_all(svcs)
    return jsonify({"service": svc, "nginx_reload": ok, "message": msg}), 201

@app.route("/api/services/<sid>", methods=["PUT"])
def update_service(sid):
    data = request.get_json()
    svcs = load_services()
    svc  = next((s for s in svcs if s["id"] == sid), None)
    if not svc:
        return jsonify({"error": "Introuvable"}), 404
    for field in ("name", "url", "icon", "enabled", "public", "public_port"):
        if field in data:
            svc[field] = data[field].rstrip("/") if field == "url" else data[field]
    save_services(svcs)
    ok, msg = apply_all(svcs)
    return jsonify({"service": svc, "nginx_reload": ok, "message": msg})

@app.route("/api/services/<sid>", methods=["DELETE"])
def delete_service(sid):
    svcs = load_services()
    new  = [s for s in svcs if s["id"] != sid]
    if len(new) == len(svcs):
        return jsonify({"error": "Introuvable"}), 404
    save_services(new)
    ok, msg = apply_all(new)
    return jsonify({"deleted": True, "nginx_reload": ok, "message": msg})

@app.route("/api/health")
def all_health():
    return jsonify([
        {"id": s["id"], "name": s["name"], **check_health(s["url"])}
        for s in load_services() if s.get("enabled")
    ])

@app.route("/api/reload", methods=["POST"])
def api_reload():
    ok, msg = apply_all(load_services())
    return jsonify({"success": ok, "message": msg})

@app.route("/api/certs")
def api_certs():
    return jsonify(cert_status())

@app.route("/api/certs/regenerate", methods=["POST"])
def api_regen():
    ok, msg = regen_certs()
    if ok:
        apply_all(load_services())
    return jsonify({"success": ok, "message": msg})

@app.route("/api/certs/download/client")
def download_client():
    p = os.path.join(DATA_CERTS, "client.p12")
    if not os.path.exists(p):
        return jsonify({"error": "client.p12 non trouvé"}), 404
    return send_file(p, as_attachment=True, download_name="proxyinha-client.p12",
                     mimetype="application/x-pkcs12")

@app.route("/api/certs/download/ca")
def download_ca():
    p = os.path.join(DATA_CERTS, "ca.crt")
    if not os.path.exists(p):
        return jsonify({"error": "ca.crt non trouvé"}), 404
    return send_file(p, as_attachment=True, download_name="proxyinha-ca.crt",
                     mimetype="application/x-x509-ca-cert")

if __name__ == "__main__":
    # Générer les configs nginx (mTLS inclus) au démarrage
    import threading, time
    def _startup_apply():
        time.sleep(3)  # Attendre que nginx soit prêt
        apply_all(load_services())
    threading.Thread(target=_startup_apply, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=False)
