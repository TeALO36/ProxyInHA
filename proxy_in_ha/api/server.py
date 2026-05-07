"""
ProxyInHA — API Server
Lightweight Flask API for managing proxy service configurations.
Persists data to /data/services.json and regenerates Nginx configs on changes.
"""

import json
import os
import subprocess
import uuid
import urllib.request
import urllib.error
from flask import Flask, jsonify, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SERVICES_DB = os.environ.get("SERVICES_DB", "/data/services.json")
NGINX_CONF_DIR = os.environ.get("NGINX_CONF_DIR", "/etc/nginx/conf.d")
INGRESS_ENTRY = os.environ.get("INGRESS_ENTRY", "/")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_services():
    """Load services from the JSON database file."""
    try:
        with open(SERVICES_DB, "r") as f:
            services = json.load(f)
            # Ensure each service has an id
            for svc in services:
                if "id" not in svc:
                    svc["id"] = str(uuid.uuid4())[:8]
            return services
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_services(services):
    """Save services to the JSON database file."""
    with open(SERVICES_DB, "w") as f:
        json.dump(services, f, indent=2)


def slugify(name):
    """Convert a service name to a URL-safe slug."""
    import re
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug


def generate_nginx_config(services):
    """Generate Nginx proxy configuration files for all enabled services."""
    # Clear existing proxy configs
    for f in os.listdir(NGINX_CONF_DIR):
        if f.startswith("proxy_") and f.endswith(".conf"):
            os.remove(os.path.join(NGINX_CONF_DIR, f))

    for svc in services:
        if not svc.get("enabled", False):
            continue

        slug = slugify(svc["name"])
        conf_path = os.path.join(NGINX_CONF_DIR, f"proxy_{slug}.conf")

        config_content = f"""# Proxy configuration for: {svc['name']}
location {INGRESS_ENTRY}proxy/{slug}/ {{
    proxy_pass {svc['url']}/;
    proxy_http_version 1.1;

    # WebSocket support
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";

    # Standard proxy headers
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;

    # Timeouts
    proxy_connect_timeout 10s;
    proxy_send_timeout 86400s;
    proxy_read_timeout 86400s;

    # Buffering
    proxy_buffering off;
    proxy_request_buffering off;
}}
"""
        with open(conf_path, "w") as f:
            f.write(config_content)


def reload_nginx():
    """Test and reload Nginx configuration."""
    # Validate first
    result = subprocess.run(
        ["nginx", "-t"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return False, result.stderr

    # Reload
    result = subprocess.run(
        ["nginx", "-s", "reload"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return False, result.stderr

    return True, "Nginx reloaded successfully"


def check_service_health(url, timeout=5):
    """Check if a service is reachable."""
    try:
        req = urllib.request.Request(url, method="GET")
        response = urllib.request.urlopen(req, timeout=timeout)
        return {
            "status": "online",
            "code": response.getcode(),
        }
    except urllib.error.HTTPError as e:
        # Even a 401/403 means the service is up
        if e.code in (401, 403):
            return {"status": "online", "code": e.code}
        return {"status": "error", "code": e.code}
    except Exception:
        return {"status": "offline", "code": None}


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------
@app.route("/api/services", methods=["GET"])
def list_services():
    """List all configured services."""
    services = load_services()
    return jsonify(services)


@app.route("/api/services", methods=["POST"])
def add_service():
    """Add a new service."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON data provided"}), 400

    # Validate required fields
    if not data.get("name") or not data.get("url"):
        return jsonify({"error": "name and url are required"}), 400

    services = load_services()

    # Check for duplicate name
    for svc in services:
        if svc["name"].lower() == data["name"].lower():
            return jsonify({"error": f"Service '{data['name']}' already exists"}), 409

    new_service = {
        "id": str(uuid.uuid4())[:8],
        "name": data["name"],
        "url": data["url"].rstrip("/"),
        "icon": data.get("icon", "mdi:server-network"),
        "enabled": data.get("enabled", True),
    }

    services.append(new_service)
    save_services(services)

    # Regenerate Nginx config and reload
    generate_nginx_config(services)
    success, msg = reload_nginx()

    return jsonify({
        "service": new_service,
        "nginx_reload": success,
        "message": msg,
    }), 201


@app.route("/api/services/<service_id>", methods=["PUT"])
def update_service(service_id):
    """Update an existing service."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON data provided"}), 400

    services = load_services()
    service = None
    for svc in services:
        if svc["id"] == service_id:
            service = svc
            break

    if not service:
        return jsonify({"error": "Service not found"}), 404

    # Update fields
    if "name" in data:
        service["name"] = data["name"]
    if "url" in data:
        service["url"] = data["url"].rstrip("/")
    if "icon" in data:
        service["icon"] = data["icon"]
    if "enabled" in data:
        service["enabled"] = data["enabled"]

    save_services(services)

    # Regenerate Nginx config and reload
    generate_nginx_config(services)
    success, msg = reload_nginx()

    return jsonify({
        "service": service,
        "nginx_reload": success,
        "message": msg,
    })


@app.route("/api/services/<service_id>", methods=["DELETE"])
def delete_service(service_id):
    """Delete a service."""
    services = load_services()
    original_len = len(services)
    services = [s for s in services if s["id"] != service_id]

    if len(services) == original_len:
        return jsonify({"error": "Service not found"}), 404

    save_services(services)

    # Regenerate Nginx config and reload
    generate_nginx_config(services)
    success, msg = reload_nginx()

    return jsonify({
        "deleted": True,
        "nginx_reload": success,
        "message": msg,
    })


@app.route("/api/services/<service_id>/health", methods=["GET"])
def service_health(service_id):
    """Check health of a specific service."""
    services = load_services()
    service = None
    for svc in services:
        if svc["id"] == service_id:
            service = svc
            break

    if not service:
        return jsonify({"error": "Service not found"}), 404

    health = check_service_health(service["url"])
    return jsonify({
        "service_id": service_id,
        "name": service["name"],
        "url": service["url"],
        **health,
    })


@app.route("/api/health", methods=["GET"])
def all_health():
    """Check health of all services."""
    services = load_services()
    results = []
    for svc in services:
        if svc.get("enabled", False):
            health = check_service_health(svc["url"])
            results.append({
                "id": svc["id"],
                "name": svc["name"],
                "url": svc["url"],
                **health,
            })
    return jsonify(results)


@app.route("/api/reload", methods=["POST"])
def api_reload():
    """Regenerate Nginx config and reload."""
    services = load_services()
    generate_nginx_config(services)
    success, msg = reload_nginx()

    return jsonify({
        "success": success,
        "message": msg,
    })


@app.route("/api/info", methods=["GET"])
def api_info():
    """Get add-on information."""
    services = load_services()
    enabled = [s for s in services if s.get("enabled", False)]
    return jsonify({
        "name": "ProxyInHA",
        "version": "1.0.0",
        "ingress_entry": INGRESS_ENTRY,
        "total_services": len(services),
        "enabled_services": len(enabled),
    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
