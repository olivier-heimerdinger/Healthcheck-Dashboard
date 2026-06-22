const ws = new WebSocket("ws://" + window.location.host + "/ws");
const container = document.getElementById("cards-container");
let serversConfig = [];

let currentChart = null;
let currentDetailedServer = null;

// ... (le reste de vos fonctions : ws.onmessage, initializeCards, etc.)
ws.onmessage = function (event) {
  var message = JSON.parse(event.data);
  if (message.type === "init") {
    serversConfig = message.servers;
    initializeCards();
  } else if (message.type === "update") {
    updateCards(message.data);
    if (currentDetailedServer) updateGraphIfOpen(message.data);
  }
};

function initializeCards() {
  container.innerHTML = "";
  serversConfig.forEach((srv) => {
    const card = document.createElement("div");
    card.id = `card-${srv.name}`;
    card.className = "server-card";
    card.onclick = () => openModal(srv.name);

    card.innerHTML = `
            <div class="card-header">
                <span class="server-name">${srv.name}</span>
                <span id="badge-${srv.name}" class="status-badge">Checking...</span>
            </div>
            <div class="server-url">${srv.url}</div>
            <div class="server-latency">Latence: <span id="latency-${srv.name}" class="latency-val">--</span> ms</div>
        `;
    container.appendChild(card);
  });
}

function updateCards(data) {
  data.forEach((srvData) => {
    const card = document.getElementById(`card-${srvData.name}`);
    const badge = document.getElementById(`badge-${srvData.name}`);
    const latencySpan = document.getElementById(`latency-${srvData.name}`);
    if (!card) return;

    if (srvData.status === "UP") {
      card.className = "server-card card-up";
      badge.className = "status-badge badge-up";
      badge.innerText = "OPÉRATIONNEL";
      latencySpan.innerText = srvData.latency;
    } else {
      card.className = "server-card card-down";
      badge.className = "status-badge badge-down";
      badge.innerText = "HORS LIGNE";
      latencySpan.innerText = "--";
    }
  });
}

// --- Logique du Modal et du Graphique ---
const modal = document.getElementById("graphModal");
const ctx = document.getElementById("historyChart").getContext("2d");

// MODIFICATION POUR RENDRE LES FONCTIONS ACCESSIBLES DEPUIS LE HTML :
window.openModal = async function (serverName) {
  currentDetailedServer = serverName;
  document.getElementById("modalServerName").innerText =
    `Historique : ${serverName}`;

  // 1. Récupération des données depuis la base de données
  const response = await fetch(
    `/api/history/${encodeURIComponent(serverName)}?limit=500`,
  );
  const history = await response.json();

  // 2. Préparation des tableaux pour Chart.js
  const labels = history.map((row) => row.time);
  const latencies = history.map((row) => row.latency);

  // 3. Astuce visuelle : Point Rouge et Gros si DOWN, Bleu et Petit si UP
  const pointColors = history.map((row) =>
    row.status === "DOWN" ? "#e74c3c" : "#3498db",
  );
  const pointRadii = history.map((row) => (row.status === "DOWN" ? 6 : 3));

  createChart(labels, latencies, pointColors, pointRadii);
  modal.style.display = "block";
};

// NOUVEAU : Mise à jour en direct avec le style conditionnel
function updateGraphIfOpen(newData) {
  const myServerData = newData.find((s) => s.name === currentDetailedServer);
  if (!myServerData) return;

  // On ajoute les nouvelles données à la fin des tableaux
  currentChart.data.labels.push(myServerData.time);
  currentChart.data.datasets[0].data.push(myServerData.latency);

  if (myServerData.status === "DOWN") {
    currentChart.data.datasets[0].pointBackgroundColor.push("#e74c3c");
    currentChart.data.datasets[0].pointBorderColor.push("#e74c3c");
    currentChart.data.datasets[0].pointRadius.push(6);
  } else {
    currentChart.data.datasets[0].pointBackgroundColor.push("#3498db");
    currentChart.data.datasets[0].pointBorderColor.push("#3498db");
    currentChart.data.datasets[0].pointRadius.push(3);
  }

  // On garde uniquement les 60 derniers points pour ne pas surcharger le visuel
  if (currentChart.data.labels.length > 500) {
    currentChart.data.labels.shift();
    currentChart.data.datasets[0].data.shift();
    currentChart.data.datasets[0].pointBackgroundColor.shift();
    currentChart.data.datasets[0].pointBorderColor.shift();
    currentChart.data.datasets[0].pointRadius.shift();
  }

  currentChart.update("none");
}

window.closeModal = function () {
  modal.style.display = "none";
  currentDetailedServer = null;
  if (currentChart) currentChart.destroy();
};

window.onclick = function (event) {
  if (event.target == document.getElementById("graphModal"))
    window.closeModal();
};

// NOUVEAU : Le graphique accepte maintenant des tableaux de données dès le départ
function createChart(labels, latencies, colors, radii) {
  if (currentChart) currentChart.destroy();
  currentChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: labels,
      datasets: [
        {
          label: "Latence (ms) | DOWN = Point Rouge",
          data: latencies,
          borderColor: "#95a5a6", // Couleur de la ligne de liaison (grise)
          backgroundColor: "rgba(149, 165, 166, 0.1)",
          pointBackgroundColor: colors, // Applique les couleurs point par point
          pointBorderColor: colors,
          pointRadius: radii, // Applique la taille point par point
          fill: true,
          tension: 0.3,
        },
      ],
    },
    options: {
      responsive: true,
      scales: {
        y: {
          beginAtZero: true,
          title: { display: true, text: "Latence (ms)" },
        },
        x: {
          title: { display: true, text: "Date & Heure" },
          ticks: {
            // Ne garde que l'heure sur l'axe X pour que ça soit lisible
            callback: function (val, index) {
              let label = this.getLabelForValue(val);
              return label ? label.split(" ")[1] : "";
            },
          },
        },
      },
      plugins: {
        tooltip: {
          callbacks: {
            label: function (context) {
              let lat = context.raw;
              return lat === 0 ? "Statut : HORS LIGNE" : `Latence : ${lat} ms`;
            },
          },
        },
        // --- NOUVEAU BLOC A AJOUTER ICI ---
        zoom: {
          pan: {
            enabled: true, // Autorise le "glisser" (scroll)
            mode: "x", // Uniquement de gauche à droite
          },
          zoom: {
            wheel: {
              enabled: true, // Autorise le zoom avec la molette
            },
            pinch: {
              enabled: true, // Autorise le zoom tactile sur mobile
            },
            mode: "x", // On zoome uniquement sur le temps, pas sur la hauteur de la latence
          },
        },
      },
    },
  });
}
