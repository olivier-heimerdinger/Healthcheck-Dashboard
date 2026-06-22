import yaml
import asyncio
import aiohttp
import time
import os
import aiosqlite
from datetime import datetime, timedelta
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.templating import Jinja2Templates
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Healthcheck Dashboard")
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Configuration GLOBALE ---
CONFIG_FILE = "cfg/config.yaml"
DB_FILE = "cfg/history.db" # Notre nouvelle base de données
current_servers = []
check_interval = 10
healthcheck_task_handle = None
main_loop = None

retention_days = 7

n8n_webhook_url = ""
n8n_auth_token = ""
alert_threshold_seconds = 30
server_state = {} # Dictionnaire pour tracker le temps de chute et l'anti-spam

async def init_db():
    """Crée la table SQLite si elle n'existe pas."""
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME,
                server_name TEXT,
                url TEXT,
                status TEXT,
                latency INTEGER
            )
        """)
        await db.commit()

def load_config():
    global current_servers, check_interval, retention_days
    try:
        with open(CONFIG_FILE, "r") as file:
            config = yaml.safe_load(file)
            current_servers = config.get("servers", [])
            check_interval = config.get("settings", {}).get("check_interval", 10)
            retention_days = config.get("retention_days", 7)

            # --- NOUVEAU : Lecture des infos n8n ---
            n8n_webhook_url = config.get("n8n_webhook_url", "")
            n8n_auth_token = config.get("n8n_auth_token", "")
            alert_threshold_seconds = config.get("alert_threshold_seconds", 30)
            
            # Initialiser le tracking d'état pour chaque serveur
            for srv in current_servers:
                if srv["name"] not in server_state:
                    server_state[srv["name"]] = {"down_since": None, "alert_sent": False}
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Configuration rechargée.")
    except Exception as e:
        print(f"Erreur chargement config: {e}")

# --- Maintenance de la Base de Données ---
async def db_maintenance_loop():
    """Tâche quotidienne pour supprimer les vieilles données et réduire la taille du fichier DB."""
    while True:
        try:
            # Calcule la date limite (ex: il y a 7 jours)
            threshold_date = (datetime.now() - timedelta(days=retention_days)).strftime("%Y-%m-%d %H:%M:%S")
            
            async with aiosqlite.connect(DB_FILE) as db:
                # 1. Supprimer les lignes trop anciennes
                cursor = await db.execute("DELETE FROM history WHERE timestamp < ?", (threshold_date,))
                deleted_rows = cursor.rowcount
                await db.commit()
                
                # 2. Réduire physiquement la taille du fichier SQLite
                if deleted_rows > 0:
                    await db.execute("VACUUM")
                    
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Maintenance DB : {deleted_rows} lignes purgées et base compressée.")
        except Exception as e:
            print(f"Erreur lors de la maintenance DB : {e}")
            
        # Attendre 24 heures (86400 secondes) avant le prochain nettoyage
        await asyncio.sleep(86400)


# --- Logique d'Alerte n8n ---
async def send_n8n_alert(session, server_name, duration_seconds, alert_type="CRITICAL_DOWN"):
    """Envoie un payload JSON au webhook n8n de manière asynchrone sécurisée."""
    if not n8n_webhook_url: return
    
    payload = {
        "server_name": server_name,
        "status": alert_type, # <-- 'CRITICAL_DOWN' ou 'RESOLVED_UP'
        "duration_seconds": int(duration_seconds), # Temps écoulé depuis la chute
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    headers = {"Content-Type": "application/json"}
    if n8n_auth_token:
        # On utilise le standard "Bearer token"
        headers["Authorization"] = f"Bearer {n8n_auth_token}"
    
    try:
        # On ajoute l'argument headers=headers ici :
        async with session.post(n8n_webhook_url, json=payload, headers=headers, timeout=5) as response:
            if response.status in [200, 201]:
                print(f"🚀 [n8n] Alerte [{alert_type}] envoyée pour {server_name}")
            elif response.status in [401, 403]:
                print(f"🔒 [n8n] Accès refusé ! Vérifiez votre n8n_auth_token.")
            else:
                print(f"⚠️ [n8n] Échec de l'envoi (Statut {response.status})")
    except Exception as e:
        print(f"❌ [n8n] Erreur de connexion au webhook : {e}")


#--- Gestionnaire de WebSockets ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        await websocket.send_json({"type": "init", "servers": current_servers})
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try: await connection.send_json(message)
            except: pass

manager = ConnectionManager()

# --- Hot Reload Logic ---
class YAMLReloadHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if not event.is_directory and os.path.basename(event.src_path) == "config.yaml":
            load_config()
            if main_loop and main_loop.is_running():
                asyncio.run_coroutine_threadsafe(restart_healthcheck(), main_loop)

# --- Logique de Healthcheck ---
async def check_server(session, server):
    status = "DOWN"
    latency = 0
    start_time = time.time()
    try:
        async with session.get(server["url"], timeout=3) as response:
            latency = int((time.time() - start_time) * 1000)
            if response.status < 400:
                status = "UP"
            else:
                latency = 0
    except Exception:
        status = "DOWN"
        latency = 0
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 1. Sauvegarde dans SQLite
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT INTO history (timestamp, server_name, url, status, latency) VALUES (?, ?, ?, ?, ?)",
            (timestamp, server["name"], server["url"], status, latency)
        )
        await db.commit()

    # --- Logique de tracking et déclenchement n8n ---
    # On exécute ce bloc UNIQUEMENT si une URL n8n est configurée

    if n8n_webhook_url:
        state = server_state[server["name"]]
        
        if status == "DOWN":
            if state["down_since"] is None:
                state["down_since"] = time.time()
                
            downtime_duration = time.time() - state["down_since"]
            
            if downtime_duration >= alert_threshold_seconds and not state["alert_sent"]:
                # Envoi de l'alerte de PANNE
                asyncio.create_task(send_n8n_alert(session, server["name"], downtime_duration, "CRITICAL_DOWN"))
                state["alert_sent"] = True
                
        else: # Si le serveur est UP
            if state["down_since"] is not None:
                # On calcule la durée totale exacte de la panne
                total_downtime = time.time() - state["down_since"]
                print(f"✅ {server['name']} est de retour en ligne après {int(total_downtime)} secondes de coupure !")
                
                # NOUVEAU : Si on avait envoyé une alerte de panne, on envoie la résolution
                if state["alert_sent"]:
                    asyncio.create_task(send_n8n_alert(session, server["name"], total_downtime, "RESOLVED_UP"))
                    
            # On réinitialise les compteurs pour la prochaine fois
            state["down_since"] = None
            state["alert_sent"] = False

    # 2. Renvoi pour le WebSocket
    return {
        "time": timestamp,
        "name": server["name"],
        "url": server["url"],
        "status": status,
        "latency": latency
    }

async def healthcheck_loop():
    async with aiohttp.ClientSession() as session:
        while True:
            servers_to_check = list(current_servers)
            if not servers_to_check:
                await asyncio.sleep(2)
                continue
            tasks = [check_server(session, srv) for srv in servers_to_check]
            results = await asyncio.gather(*tasks)
            await manager.broadcast({"type": "update", "data": results})
            await asyncio.sleep(check_interval)

async def restart_healthcheck():
    global healthcheck_task_handle
    if healthcheck_task_handle: healthcheck_task_handle.cancel()
    await manager.broadcast({"type": "init", "servers": current_servers})
    healthcheck_task_handle = asyncio.create_task(healthcheck_loop())

# --- Événements de cycle de vie ---
@app.on_event("startup")
async def startup_event():
    global healthcheck_task_handle, main_loop
    main_loop = asyncio.get_running_loop()
    
    await init_db() # Création de la DB au démarrage
    load_config()
    
    config_dir = os.path.dirname(CONFIG_FILE)
    observer = Observer()
    observer.schedule(YAMLReloadHandler(), path=config_dir, recursive=False)
    observer.start()
    
    healthcheck_task_handle = asyncio.create_task(healthcheck_loop())
    asyncio.create_task(db_maintenance_loop())

# --- Routes REST et WS ---
@app.get("/")
async def get_dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

# NOUVELLE ROUTE : Récupérer l'historique d'un serveur pour le graphique
@app.get("/api/history/{server_name}")
async def get_server_history(server_name: str, limit: int = 60):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        # On récupère les X dernières entrées
        cursor = await db.execute(
            "SELECT timestamp as time, status, latency FROM history WHERE server_name = ? ORDER BY timestamp DESC LIMIT ?",
            (server_name, limit)
        )
        rows = await cursor.fetchall()
        # On inverse pour avoir l'ordre chronologique (du plus vieux au plus récent)
        return [dict(row) for row in reversed(rows)]

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
