"""
ProxyInHA v1.1.0 — API Server
Flask API for managing proxy services including mTLS public exposure.
"""

import json
import os
import re
import subprocess
import uuid
import urllib.request
import urllib.error
from flask import Flask, jsonify, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
SERVICES_DB   = os.environ.get("SERVICES_DB",   "/data/services.json")
NGINX_CONF_DIR = os.environ.get("NGINX_CONF_DIR", "/etc/nginx/conf.d")
MTLS_CONF_DIR  = os.environ.get("MTLS_CONF_DIR",  "/etc/nginx/mtls.d")
CERTS_DIR      = os.environ.get("CERTS_DIR",      "/etc/nginx/certs")
DOMAIN         = os.environ.get("DOMAIN",         "")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_services():
    try:
        with open(SERVICES_DB) as f:
            services = json.load(f)
        for svc in services:
            if "id" not in svc:
                svc["id"] = str(uuid.uuid4())[:8]
        return services
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_services(services):
    with open(SERVICES_DB, "w") as f:
        json.dump(services, f, indent=2)

def slugify(name):
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")

def generate_internal_config(services):
    """Generate nginx location blocks for internal (ingress) proxy."""
    for f in os.listdir(NGINX_CONF_DIR):
        if f.startswith("proxy_") and f.endswith(".conf"):
            os.remove(os.path.join(NGINX_CONF_DIR, f))

    for svc in services:
        if not svc.get("enabled", False):
            continue
        slug = slugify(svc["name"])
        url  = svc["url"].rstrip("/")
        conf = f"""location /proxy/{slug}/ {{
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
}}
"""
        with open(os.path.join(NGINX_CONF_DIR, f"proxy_{slug}.conf"), "w") as f_out:
            f_out.write(conf)

def generate_mtls_config(services):
    """Generate nginx server blocks for public mTLS-protected services."""
    for f in os.listdir(MTLS_CONF_DIR):
        if f.endswith(".conf"):
            os.remove(os.path.join(MTLS_CONF_DIR, f))

    server_crt = os.path.join(CERTS_DIR, "server.crt")
    server_key = os.path.join(CERTS_DIR, "server.key")
    ca_crt     = os.path.join(CERTS_DIR, "ca.crt")

    if not os.path.exists(server_crt) or not os.path.exists(server_key):
        return  # No TLS certs available

    ca_block = ""
    if os.path.exists(ca_crt):
        ca_block = f"""
    ssl_client_certificate {ca_crt};
    ssl_verify_client on;"""

    for svc in services:
        if not svc.get("enabled", False):
            continue
        if not svc.get("public", False):
            continue
        port = svc.get("public_port")
        if not port:
            continue

        slug = slugify(svc["name"])
        url  = svc["url"].rstrip("/")
        server_name = DOMAIN if DOMAIN else "_"

        conf = f"""server {{
    listen {port} ssl;
    server_name {server_name};

    ssl_certificate     {server_crt};
    ssl_certificate_key {server_key};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL_{slug}:10m;
    ssl_session_timeout 1d;
{ca_block}

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
}}
"""
        with open(os.path.join(MTLS_CONF_DIR, f"mtls_{slug}.conf"), "w") as f_out:
            f_out.write(conf)

def reload_nginx():
    r = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
    if r.returncode != 0:
        return False, r.stderr
    r = subprocess.run(["nginx", "-s", "reload"], capture_output=True, text=True)
    if r.returncode != 0:
        return False, r.stderr
    return True, "Nginx rechargé"

def apply_config(services):
    generate_internal_config(services)
    generate_mtls_config(services)
    return reload_nginx()

def check_health(url, timeout=5):
    try:
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=timeout)
        return {"status": "online", "code": resp.getcode()}
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 302):
            return {"status": "online", "code": e.code}
        return {"status": "error", "code": e.code}
    except Exception:
        return {"status": "offline", "code": None}

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/api/info")
def api_info():
    services = load_services()
    enabled  = [s for s in services if s.get("enabled")]
    public   = [s for s in services if s.get("public") and s.get("enabled")]
    certs = {
        "server_cert": os.path.exists(os.path.join(CERTS_DIR, "server.crt")),
        "server_key":  os.path.exists(os.path.join(CERTS_DIR, "server.key")),
        "ca_cert":     os.path.exists(os.path.join(CERTS_DIR, "ca.crt")),
    }
    return jsonify({
        "version": "1.1.0",
        "domain": DOMAIN,
        "total_services": len(services),
        "enabled_services": len(enabled),
        "public_mtls_services": len(public),
        "certs": certs,
    })

@app.route("/api/services")
def list_services():
    return jsonify(load_services())

@app.route("/api/services", methods=["POST"])
def add_service():
    data = request.get_json()
    if not data or not data.get("name") or not data.get("url"):
        return jsonify({"error": "name et url sont requis"}), 400

    services = load_services()
    if any(s["name"].lower() == data["name"].lower() for s in services):
        return jsonify({"error": f"Service '{data['name']}' existe déjà"}), 409

    svc = {
        "id":          str(uuid.uuid4())[:8],
        "name":        data["name"],
        "url":         data["url"].rstrip("/"),
        "icon":        data.get("icon", "mdi:server-network"),
        "enabled":     data.get("enabled", True),
        "public":      data.get("public", False),
        "public_port": data.get("public_port") or None,
    }
    services.append(svc)
    save_services(services)
    ok, msg = apply_config(services)
    return jsonify({"service": svc, "nginx_reload": ok, "message": msg}), 201

@app.route("/api/services/<sid>", methods=["PUT"])
def update_service(sid):
    data = request.get_json()
    services = load_services()
    svc = next((s for s in services if s["id"] == sid), None)
    if not svc:
        return jsonify({"error": "Service introuvable"}), 404

    for field in ("name", "url", "icon", "enabled", "public", "public_port"):
        if field in data:
            val = data[field]
            if field == "url":
                val = val.rstrip("/")
            svc[field] = val

    save_services(services)
    ok, msg = apply_config(services)
    return jsonify({"service": svc, "nginx_reload": ok, "message": msg})

@app.route("/api/services/<sid>", methods=["DELETE"])
def delete_service(sid):
    services = load_services()
    new = [s for s in services if s["id"] != sid]
    if len(new) == len(services):
        return jsonify({"error": "Service introuvable"}), 404
    save_services(new)
    ok, msg = apply_config(new)
    return jsonify({"deleted": True, "nginx_reload": ok, "message": msg})

@app.route("/api/services/<sid>/health")
def service_health(sid):
    svc = next((s for s in load_services() if s["id"] == sid), None)
    if not svc:
        return jsonify({"error": "Service introuvable"}), 404
    return jsonify({"id": sid, "name": svc["name"], **check_health(svc["url"])})

@app.route("/api/health")
def all_health():
    results = []
    for svc in load_services():
        if svc.get("enabled"):
            results.append({"id": svc["id"], "name": svc["name"],
                            **check_health(svc["url"])})
    return jsonify(results)

@app.route("/api/reload", methods=["POST"])
def api_reload():
    ok, msg = apply_config(load_services())
    return jsonify({"success": ok, "message": msg})

@app.route("/api/certs")
def api_certs():
    return jsonify({
        "server_cert": os.path.exists(os.path.join(CERTS_DIR, "server.crt")),
        "server_key":  os.path.exists(os.path.join(CERTS_DIR, "server.key")),
        "ca_cert":     os.path.exists(os.path.join(CERTS_DIR, "ca.crt")),
        "domain": DOMAIN,
    })

# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
