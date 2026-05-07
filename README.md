# ProxyInHA — Reverse Proxy pour Home Assistant

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Add--on-blue?logo=homeassistant&logoColor=white)](https://www.home-assistant.io/)
[![Version](https://img.shields.io/badge/version-1.0.0-green)](https://github.com/TeALO36/ProxyInHA/releases)
[![License](https://img.shields.io/badge/license-MIT-purple)](LICENSE)

> Accédez à tous vos services locaux depuis n'importe quel réseau via Home Assistant, sans ouvrir de ports supplémentaires.

## 🛡️ Pourquoi ProxyInHA ?

Vous avez Home Assistant exposé de manière sécurisée (mTLS, Nabu Casa, etc.) mais vous devez aussi accéder à Portainer, Grafana, Pi-hole et d'autres services locaux quand vous n'êtes pas chez vous ?

**ProxyInHA** résout ce problème en agissant comme un **reverse proxy interne** directement dans Home Assistant :

- 🔒 **Pas de ports ouverts** — Tout passe par le tunnel sécurisé de HA
- 🌐 **Accès à tous vos services** — Portainer, Grafana, Pi-hole, Node-RED...
- 🎨 **Interface premium** — Dashboard moderne avec statut en temps réel
- ⚡ **Configuration dynamique** — Ajoutez/supprimez des services sans redémarrer
- 📊 **Health checks** — Vérification automatique de l'état de vos services

## 📦 Installation

### 1. Ajouter le dépôt

Dans Home Assistant :
1. Allez dans **Paramètres** → **Modules complémentaires** → **Boutique des modules complémentaires**
2. Cliquez sur **⋮** (trois points en haut à droite) → **Dépôts**
3. Ajoutez l'URL : `https://github.com/TeALO36/ProxyInHA`
4. Cliquez sur **Ajouter** puis rafraîchissez

### 2. Installer l'add-on

1. Cherchez **ProxyInHA** dans la boutique
2. Cliquez sur **Installer**
3. Activez **Afficher dans la barre latérale**
4. Démarrez l'add-on

## 🚀 Utilisation

1. Ouvrez **ProxyInHA** depuis la barre latérale
2. Cliquez sur **Ajouter un service**
3. Renseignez le nom, l'URL locale (ex: `http://192.168.0.100:9000`) et une icône
4. Le service est immédiatement accessible via le proxy !

## ⚙️ Configuration

| Option | Description | Défaut |
|--------|------------|--------|
| `services` | Liste des services à proxifier | `[]` |
| `check_interval` | Intervalle des health checks (secondes) | `30` |

### Exemple de service

```yaml
services:
  - name: Portainer
    url: http://192.168.0.100:9000
    icon: mdi:docker
    enabled: true
  - name: Grafana
    url: http://192.168.0.100:3000
    icon: mdi:chart-line
    enabled: true
```

## 🏗️ Architecture

```
Utilisateur externe → [mTLS] → Home Assistant → [Ingress] → ProxyInHA → [proxy_pass] → Service local
```

L'add-on utilise **Nginx** comme reverse proxy et une **API Flask** pour la gestion dynamique des services.

## 📝 Licence

MIT — Utilisez-le, modifiez-le, partagez-le !

---

*Développé par [TeALO36](https://github.com/TeALO36)*
