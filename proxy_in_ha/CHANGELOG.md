# Changelog

## [1.0.2] - 2025-05-07

### Corrigé
- Suppression de la page "Welcome to nginx!" (config Alpine par défaut)
- Suppression de la substitution `%%INGRESS_ENTRY%%` — HA ingress gère lui-même le routing
- Utilisation de `exec python3` pour garder Flask en foreground (PID principal)
- Logs nginx vers stderr/stdout pour visibilité dans HA
- `dos2unix` appliqué au build pour les fins de ligne Windows

## [1.0.1] - 2025-05-07

### Corrigé
- Tentative de fix nginx default page

## [1.0.0] - 2025-05-07

## [1.0.0] - 2025-05-07

### Ajouté
- Reverse proxy Nginx pour les services locaux
- Interface web d'administration (dashboard)
- API REST pour la gestion des services (CRUD)
- Health checks automatiques avec statut temps réel
- Support WebSocket complet
- Support ingress Home Assistant (pas de port exposé)
- Panneau dans la barre latérale HA
- Rechargement Nginx à chaud (sans redémarrage)
- Traductions français et anglais
- Design dark mode premium avec glassmorphism
