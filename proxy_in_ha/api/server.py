"""ProxyInHA v1.2.0 — API Server with cert management"""

import json, os, re, subprocess, uuid, urllib.request, urllib.error
from flask import Flask, jsonify, request, send_file

app = Flask(__name__)

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
    with open(SERVICES_DB, "w") as f:
        json.dump(svcs, f, indent=2)

def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

def run_cmd(*args):
    r = subprocess.run(list(args), capture_output=True, text=True)
    return r.returncode == 0, r.stdout + r.stderr

def reload_nginx():
    ok, _ = run_cmd("nginx", "-t")
    if not ok: return False, "Config nginx invalide"
    ok, msg = run_cmd("nginx", "-s", "reload")
    return ok, msg or "Nginx rechargé"

def generate_internal_conf(svcs):
    for f in os.listdir(NGINX_CONF_DIR):
        if f.startswith("proxy_") and f.endswith(".conf"):
            os.remove(os.path.join(NGINX_CONF_DIR, f))
    for svc in svcs:
        if not svc.get("enabled"): continue
        slug = slugify(svc["name"])
        url  = svc["url"].rstrip("/")
        with open(os.path.join(NGINX_CONF_DIR, f"proxy_{slug}.conf"), "w") as f:
            f.write(f"""location /proxy/{slug}/ {{
    proxy_pass {url}/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_connect_timeout 10s;
    proxy_send_timeout 86400s;
    proxy_read_timeout 86400s;
    proxy_buffering off;
}}\n""")

def generate_mtls_conf(svcs):
    for f in os.listdir(MTLS_CONF_DIR):
        if f.endswith(".conf"): os.remove(os.path.join(MTLS_CONF_DIR, f))

    server_crt = os.path.join(NGINX_CERTS, "server.crt")
    server_key = os.path.join(NGINX_CERTS, "server.key")
    ca_crt     = os.path.join(NGINX_CERTS, "ca.crt")

    if not os.path.exists(server_crt) or not os.path.exists(server_key):
        return

    ca_block = ""
    if os.path.exists(ca_crt):
        ca_block = f"\n    ssl_client_certificate {ca_crt};\n    ssl_verify_client on;"

    sn = DOMAIN or "_"
    for svc in svcs:
        if not svc.get("enabled") or not svc.get("public") or not svc.get("public_port"):
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
    ssl_session_cache shared:SSL_{slug}:10m;
    ssl_session_timeout 1d;{ca_block}

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
        proxy_connect_timeout 10s;
        proxy_send_timeout 86400s;
        proxy_read_timeout 86400s;
        proxy_buffering off;
    }}
}}\n""")

def apply_all(svcs):
    generate_internal_conf(svcs)
    generate_mtls_conf(svcs)
    return reload_nginx()

def check_health(url, timeout=5):
    try:
        resp = urllib.request.urlopen(urllib.request.Request(url), timeout=timeout)
        return {"status": "online", "code": resp.getcode()}
    except urllib.error.HTTPError as e:
        return {"status": "online" if e.code in (401, 403, 302, 200) else "error", "code": e.code}
    except Exception:
        return {"status": "offline", "code": None}

def cert_status():
    return {
        "server_cert": os.path.exists(os.path.join(NGINX_CERTS, "server.crt")),
        "server_key":  os.path.exists(os.path.join(NGINX_CERTS, "server.key")),
        "ca_cert":     os.path.exists(os.path.join(NGINX_CERTS, "ca.crt")),
        "client_p12":  os.path.exists(os.path.join(DATA_CERTS, "client.p12")),
        "client_crt":  os.path.exists(os.path.join(DATA_CERTS, "client.crt")),
        "tls_mode":    TLS_MODE,
        "domain":      DOMAIN,
    }

def regen_certs():
    """Régénère tous les certificats auto-signés."""
    domain = DOMAIN or "proxyinha.local"
    d = DATA_CERTS
    os.makedirs(d, exist_ok=True)

    cmds = [
        # CA
        ["openssl", "genrsa", "-out", f"{d}/ca.key", "4096"],
        ["openssl", "req", "-new", "-x509", "-days", "3650",
         "-key", f"{d}/ca.key", "-out", f"{d}/ca.crt",
         "-subj", "/C=FR/ST=France/O=ProxyInHA/CN=ProxyInHA Root CA"],
        # Server key + CSR
        ["openssl", "genrsa", "-out", f"{d}/server.key", "2048"],
        ["openssl", "req", "-new", "-key", f"{d}/server.key",
         "-out", f"{d}/server.csr",
         "-subj", f"/C=FR/ST=France/O=ProxyInHA/CN={domain}"],
    ]
    ext = f"[v3_req]\nsubjectAltName = @alt_names\n[alt_names]\nDNS.1 = {domain}\nDNS.2 = localhost\nIP.1 = 127.0.0.1\n"
    with open("/tmp/server_ext.cnf", "w") as f:
        f.write(ext)
    cmds += [
        ["openssl", "x509", "-req", "-days", "825",
         "-in", f"{d}/server.csr", "-CA", f"{d}/ca.crt", "-CAkey", f"{d}/ca.key",
         "-CAcreateserial", "-out", f"{d}/server.crt",
         "-extfile", "/tmp/server_ext.cnf", "-extensions", "v3_req"],
        # Client cert
        ["openssl", "genrsa", "-out", f"{d}/client.key", "2048"],
        ["openssl", "req", "-new", "-key", f"{d}/client.key",
         "-out", f"{d}/client.csr",
         "-subj", "/C=FR/ST=France/O=ProxyInHA/CN=ProxyInHA Client"],
        ["openssl", "x509", "-req", "-days", "825",
         "-in", f"{d}/client.csr", "-CA", f"{d}/ca.crt", "-CAkey", f"{d}/ca.key",
         "-CAcreateserial", "-out", f"{d}/client.crt"],
        # p12
        ["openssl", "pkcs12", "-export",
         "-in", f"{d}/client.crt", "-inkey", f"{d}/client.key",
         "-certfile", f"{d}/ca.crt", "-out", f"{d}/client.p12",
         "-passout", "pass:proxyinha"],
    ]
    for cmd in cmds:
        ok, err = run_cmd(*cmd)
        if not ok:
            return False, f"Erreur: {' '.join(cmd[:3])}: {err}"

    import shutil
    shutil.copy(f"{d}/server.crt", os.path.join(NGINX_CERTS, "server.crt"))
    shutil.copy(f"{d}/server.key", os.path.join(NGINX_CERTS, "server.key"))
    shutil.copy(f"{d}/ca.crt",    os.path.join(NGINX_CERTS, "ca.crt"))
    os.chmod(os.path.join(NGINX_CERTS, "server.key"), 0o600)
    return True, "Certificats régénérés"

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/api/info")
def api_info():
    svcs = load_services()
    cs = cert_status()
    return jsonify({
        "version": "1.2.0",
        "domain": DOMAIN,
        "tls_mode": TLS_MODE,
        "total_services": len(svcs),
        "enabled_services": sum(1 for s in svcs if s.get("enabled")),
        "public_services": sum(1 for s in svcs if s.get("public") and s.get("enabled")),
        "certs": cs,
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
        return jsonify({"error": f"Service '{data['name']}' existe déjà"}), 409
    svc = {
        "id": str(uuid.uuid4())[:8],
        "name": data["name"],
        "url": data["url"].rstrip("/"),
        "icon": data.get("icon", "mdi:server-network"),
        "enabled": data.get("enabled", True),
        "public": data.get("public", False),
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
    svc = next((s for s in svcs if s["id"] == sid), None)
    if not svc: return jsonify({"error": "Service introuvable"}), 404
    for field in ("name", "url", "icon", "enabled", "public", "public_port"):
        if field in data:
            svc[field] = data[field].rstrip("/") if field == "url" else data[field]
    save_services(svcs)
    ok, msg = apply_all(svcs)
    return jsonify({"service": svc, "nginx_reload": ok, "message": msg})

@app.route("/api/services/<sid>", methods=["DELETE"])
def delete_service(sid):
    svcs = load_services()
    new = [s for s in svcs if s["id"] != sid]
    if len(new) == len(svcs): return jsonify({"error": "Introuvable"}), 404
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
        return jsonify({"error": "client.p12 non trouvé — générez d'abord les certs"}), 404
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
    app.run(host="127.0.0.1", port=5000, debug=False)
