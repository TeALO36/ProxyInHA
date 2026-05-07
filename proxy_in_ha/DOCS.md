# ProxyInHA — Documentation

## Vue d'ensemble

ProxyInHA est un add-on Home Assistant qui agit comme un reverse proxy,
vous permettant d'accéder à vos services locaux depuis n'importe quel réseau
via la connexion sécurisée (mTLS) de Home Assistant.

**Avantage principal** : aucun port supplémentaire à ouvrir sur votre routeur.

## Prérequis

- Home Assistant OS ou Supervised
- Home Assistant accessible depuis l'extérieur (Nabu Casa, mTLS, VPN, etc.)
- Services locaux accessibles depuis la machine HA (même réseau)

## Configuration

### Options

| Option | Type | Requis | Défaut | Description |
|--------|------|--------|--------|-------------|
| `services` | liste | Non | `[]` | Services à proxifier |
| `check_interval` | entier | Non | `30` | Intervalle des health checks (5-300s) |

### Structure d'un service

| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `name` | texte | Oui | Nom affiché dans le dashboard |
| `url` | URL | Oui | URL complète du service local |
| `icon` | texte | Non | Icône Material Design (ex: `mdi:docker`) |
| `enabled` | booléen | Oui | Active/désactive le proxy pour ce service |

### Exemple

```yaml
services:
  - name: Portainer
    url: http://192.168.0.100:9000
    icon: mdi:docker
    enabled: true
  - name: Pi-hole
    url: http://192.168.0.1:80
    icon: mdi:shield-check
    enabled: true
  - name: Grafana
    url: http://192.168.0.100:3000
    icon: mdi:chart-line
    enabled: true
```

## Utilisation

### Dashboard

Le dashboard est accessible depuis la barre latérale de Home Assistant
(icône bouclier réseau). Il affiche :

- **Tous vos services** avec leur statut (en ligne / hors ligne)
- **Ajout rapide** de nouveaux services via le formulaire
- **Actions** : ouvrir, modifier, supprimer chaque service

### Ajouter un service

1. Cliquez sur **"Ajouter un service"** dans le dashboard
2. Remplissez les champs :
   - **Nom** : nom descriptif (ex: "Portainer")
   - **URL** : adresse locale complète (ex: `http://192.168.0.100:9000`)
   - **Icône** : icône MDI optionnelle (voir [materialdesignicons.com](https://materialdesignicons.com))
   - **Activé** : cochez pour activer le proxy immédiatement
3. Cliquez sur **Ajouter** — Nginx se recharge automatiquement

### Accéder à un service

Cliquez sur le bouton **"Ouvrir"** sur la carte du service dans le dashboard.
Le service s'ouvre dans un nouvel onglet via le reverse proxy de HA.

### Health Checks

L'add-on vérifie automatiquement l'état de chaque service activé.
Le statut est affiché sur chaque carte :

- 🟢 **En ligne** : le service répond correctement
- 🔴 **Hors ligne** : le service ne répond pas
- 🟡 **Vérification** : en cours de vérification

## Résolution de problèmes

### Le service affiche "Hors ligne"

1. Vérifiez que le service est bien démarré sur la machine cible
2. Vérifiez que l'URL est correcte (IP et port)
3. Vérifiez que la machine HA peut joindre le service (`ping`, `curl`)

### Le proxy ne fonctionne pas

1. Vérifiez les logs de l'add-on dans HA
2. Cliquez sur le bouton **Recharger Nginx** dans le dashboard
3. Redémarrez l'add-on si nécessaire

### WebSocket ne fonctionne pas

Le proxy supporte nativement les WebSockets. Si vous avez des problèmes,
vérifiez que votre service utilise un chemin WebSocket standard.

## Architecture technique

```
┌─────────────────────────────────────────────┐
│                  ProxyInHA                   │
│                                             │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐  │
│  │  Nginx   │  │ Flask API│  │ Health    │  │
│  │ (proxy)  │←→│ (config) │  │ Checker   │  │
│  └────┬─────┘  └──────────┘  └───────────┘  │
│       │                                      │
└───────┼──────────────────────────────────────┘
        │
   ┌────┴────┐  ┌─────────┐  ┌──────────┐
   │Portainer│  │ Grafana  │  │ Pi-hole  │  ...
   │ :9000   │  │  :3000   │  │   :80    │
   └─────────┘  └─────────┘  └──────────┘
```

## Support

Pour signaler un bug ou demander une fonctionnalité :
[GitHub Issues](https://github.com/TeALO36/ProxyInHA/issues)
