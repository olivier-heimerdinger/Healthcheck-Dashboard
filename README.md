# 🩺 Healthcheck Dashboard

Un tableau de bord de supervision de serveurs léger, asynchrone et en temps réel, propulsé par **FastAPI** et **WebSockets**. 
Ce projet permet de surveiller l'état de vos sites et API, de conserver un historique dans une base de données SQLite, et d'envoyer des alertes intelligentes vers **n8n**.

## ✨ Fonctionnalités

* ⚡ **Asynchrone & Performant :** Pings non-bloquants utilisant `aiohttp` et `FastAPI`.
* 🟢 **Temps Réel (WebSockets) :** Mise à jour instantanée de l'interface sans aucun rafraîchissement de page.
* 📊 **Graphiques Interactifs :** Visualisation de la latence et des coupures (Chart.js) avec zoom et défilement temporel.
* 🔄 **Hot-Reload :** Modification du fichier de configuration `config.yaml` prise en compte à la volée, sans redémarrer le serveur (via `watchdog`).
* 🗄️ **Stockage Persistant :** Historique sauvegardé dans une base de données **SQLite** (`aiosqlite`) avec une tâche de maintenance automatisée (purge des anciennes données et compression).
* 🚨 **Alertes Intelligentes (n8n) :** Envoi de webhooks pour les événements `CRITICAL_DOWN` et `RESOLVED_UP`, intégrant un système anti-spam et le calcul précis du temps de coupure.

---

## 📂 Architecture du Projet

    Healthcheck/
    ├── main.py                 # Cœur de l'application (Backend FastAPI)
    ├── cfg/
    │   ├── config.yaml         # Fichier de configuration (URL, intervalles, n8n)
    │   └── history.db          # Base de données SQLite (générée automatiquement)
    ├── templates/
    │   └── index.html          # Structure de la page web
    └── static/
        ├── css/
        │   └── style.css       # Styles (Cartes, Glassmorphism, Responsive)
        └── js/
            └── app.js          # Logique front-end (WebSockets, Chart.js)

---

## 🚀 Installation & Démarrage

### 1. Prérequis
Assurez-vous d'avoir Python 3.8+ installé. Il est recommandé d'utiliser un environnement virtuel.

    python -m venv .venv
    # Activation sous Windows :
    .\.venv\Scripts\activate
    # Activation sous Linux/Mac :
    source .venv/bin/activate

### 2. Installation des dépendances
    pip install fastapi uvicorn websockets pyyaml aiohttp jinja2 watchdog aiosqlite aiofiles

### 3. Lancement du serveur
    uvicorn main:app --reload

Le tableau de bord sera accessible à l'adresse : http://localhost:8000

---

## ⚙️ Configuration (cfg/config.yaml)

Toute la configuration s'effectue dans le fichier `config.yaml`. **Toute modification de ce fichier en cours de route est appliquée immédiatement !**

    settings:
      check_interval: 5               # Fréquence des pings en secondes
      retention_days: 7               # Durée de conservation de l'historique SQLite
      n8n_webhook_url: "https://votre-n8n.com/webhook/server-down" # URL Webhook (Optionnel)
      alert_threshold_seconds: 30     # Délai avant déclenchement de l'alerte de panne

    servers:
      - name: "Serveur Principal"
        url: "https://votre-site.com"
      - name: "API de Test"
        url: "https://api-a-surveiller.com/ping"

---

## 🤖 Intégration n8n (Webhooks)

Si une URL est renseignée dans `n8n_webhook_url`, l'application enverra automatiquement des payloads JSON à votre orchestrateur.

**Exemple de payload envoyé lors d'une panne (CRITICAL_DOWN) :**
    {
      "server_name": "Serveur Principal",
      "status": "CRITICAL_DOWN",
      "downtime_seconds": 30,
      "timestamp": "2024-05-24 10:31:45"
    }

**Exemple de payload envoyé lors de la résolution (RESOLVED_UP) :**
    {
      "server_name": "Serveur Principal",
      "status": "RESOLVED_UP",
      "duration_seconds": 185,
      "timestamp": "2024-05-24 10:34:50"
    }

*Note : Si la panne dure moins longtemps que `alert_threshold_seconds`, aucune alerte n'est envoyée pour éviter le spam lors de micro-coupures réseau.*

---

## 🛠️ Stack Technique

* **Backend :** Python, FastAPI, Uvicorn, asyncio, aiohttp, aiosqlite, watchdog
* **Frontend :** HTML5, CSS3, Vanilla JS (ES6 Modules)
* **Graphiques :** Chart.js avec plugin chartjs-plugin-zoom (Hammer.js)

---

## 📄 Licence
Ce projet est sous licence MIT. Vous êtes libre de l'utiliser, de le modifier et de le distribuer.