// Rozpoczęcie sesji
async function startSession() {
    const name = document.getElementById('sessionName').value;
    const flight = parseInt(document.getElementById('flightDuration').value);
    const prep = parseInt(document.getElementById('prepDuration').value);

    const response = await fetch('/api/session/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            name: name,
            flight_duration_sec: flight,
            prep_duration_sec: prep
        })
    });

    const result = await response.json();
    if(response.ok) {
        alert(result.message);
    } else {
        alert("Błąd: " + result.detail);
    }
}

// Zatrzymanie sesji
async function stopSession() {
    const response = await fetch('/api/session/stop', { method: 'POST' });
    const result = await response.json();
    alert(result.message);
}

// Dodawanie pilota i wymuszanie rebalansingu
async function addPilot() {
    const name = document.getElementById('pilotName').value.trim();
    const system = document.getElementById('pilotSystem').value;
    const isDigital = (system === 'digital');

    if (!name) {
        alert("Podaj nick/imię pilota.");
        return;
    }

    const response = await fetch('/api/pilots', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            name: name,
            is_active: true,
            digital: isDigital
        })
    });

    const result = await response.json();
    if (response.ok) {
        fetchGroups();
        document.getElementById('pilotName').value = "";
    } else {
        alert("Błąd: " + result.detail);
    }
}

function setPauseButton(paused) {
    const btn = document.getElementById('pauseResumeBtn');
    if (!btn) return;
    btn.innerText = paused ? 'Wznów' : 'Pauza';
    btn.style.backgroundColor = paused ? '#28a745' : '#6c757d';
}
async function togglePauseSession() {
    const phaseText = (document.getElementById("phaseDisplay").innerText || "").toLowerCase();
    const isPaused = phaseText.includes("pauza");

    const endpoint = isPaused ? '/api/cycle/resume' : '/api/cycle/pause';
    const response = await fetch(endpoint, { method: 'POST' });
    const result = await response.json();

    if (!response.ok) {
        alert("Błąd: " + (result.detail || "Nie udało się zmienić stanu pauzy."));
        return;
    }

    if (isPaused) {
        setPauseButton(false);
    } else {
        setPauseButton(true);
        document.getElementById("phaseDisplay").innerText = "Faza: Oczekiwanie / Pauza";
    }
}

async function skipPhase() {
    const response = await fetch('/api/cycle/skip', { method: 'POST' });
    const result = await response.json();

    if (response.ok) {
        alert(result.message);
        fetchGroups();
    } else {
        alert("Błąd: " + (result.detail || "Nie udało się pominąć etapu."));
    }
}



async function removePilot(pilotId) {
    const response = await fetch(`/api/pilots/${pilotId}`, { method: 'DELETE' });
    const result = await response.json();

    if (response.ok) {
        fetchGroups();
    } else {
        alert("Błąd: " + (result.detail || "Nie udało się usunąć pilota."));
    }
}

let lastGroupsFetchTs = 0;
let cachedGroups = { groups: [], current_index: 0 };

function refreshGroupsThrottled(minIntervalMs = 1200) {
    const now = Date.now();
    if (now - lastGroupsFetchTs >= minIntervalMs) {
        lastGroupsFetchTs = now;
        fetchGroups();
    }
}

function updatePilotsDisplay() {
    const { groups, current_index } = cachedGroups;

    const currentPilotsDiv = document.getElementById('currentPilots');
    const nextPilotsDiv = document.getElementById('nextPilots');

    if (!groups || groups.length === 0) {
        currentPilotsDiv.innerHTML = '';
        nextPilotsDiv.innerHTML = '';
        return;
    }

    // Bieżąca grupa
    const currentGroup = groups[current_index];
    let currentHtml = `<div><strong>🟢 Grupa ${currentGroup.id}</strong></div>`;

    const sortedCurrentPilots = [...currentGroup.pilots].sort((a, b) => {
        const channelA = currentGroup.channels[a.id] || '';
        const channelB = currentGroup.channels[b.id] || '';
        return channelA.localeCompare(channelB, 'pl', { numeric: true, sensitivity: 'base' });
    });

    sortedCurrentPilots.forEach(pilot => {
        const channel = currentGroup.channels[pilot.id];
        const sysIcon = pilot.digital ? '📺' : '📻';
        currentHtml += `<div>${sysIcon} ${pilot.name} (${channel})</div>`;
    });

    currentPilotsDiv.innerHTML = currentHtml;

    // Następna grupa (jeśli istnieje)
    const nextIndex = (current_index + 1) % groups.length;
    if (nextIndex !== current_index) {
        const nextGroup = groups[nextIndex];
        let nextHtml = `<div><strong>⏭️ Grupa ${nextGroup.id}</strong></div>`;

        const sortedNextPilots = [...nextGroup.pilots].sort((a, b) => {
            const channelA = nextGroup.channels[a.id] || '';
            const channelB = nextGroup.channels[b.id] || '';
            return channelA.localeCompare(channelB, 'pl', { numeric: true, sensitivity: 'base' });
        });

        sortedNextPilots.forEach(pilot => {
            const channel = nextGroup.channels[pilot.id];
            const sysIcon = pilot.digital ? '📺' : '📻';
            nextHtml += `<div>${sysIcon} ${pilot.name} (${channel})</div>`;
        });

        nextPilotsDiv.innerHTML = nextHtml;
    } else {
        nextPilotsDiv.innerHTML = '';
    }
}

// Pobieranie aktualnego stanu grup
async function fetchGroups() {
    lastGroupsFetchTs = Date.now();
    const response = await fetch('/api/groups');
    const data = await response.json();

    cachedGroups = data;
    updatePilotsDisplay();

    const container = document.getElementById('groupsContainer');
    container.innerHTML = '';

    if (!data.groups || data.groups.length === 0) {
        container.innerHTML = '<p>Brak wygenerowanych grup.</p>';
        return;
    }

    data.groups.forEach(group => {
        let isCurrent = (data.current_index === (group.id - 1)) ? ' 🟢 (Teraz leci)' : '';
        let groupHtml = `<div class="group-card"><h3>Grupa ${group.id} ${isCurrent}</h3><ul>`;

        const sortedPilots = [...group.pilots].sort((a, b) => {
            const channelA = group.channels[a.id] || '';
            const channelB = group.channels[b.id] || '';
            return channelA.localeCompare(channelB, 'pl', { numeric: true, sensitivity: 'base' });
        });

        sortedPilots.forEach(pilot => {
            let channel = group.channels[pilot.id];
            let sysIcon = pilot.digital ? '📺 (Cyfra)' : '📻 (Analog)';
            groupHtml += `
                <li>
                    <strong>${pilot.name}</strong> (ID: ${pilot.id}) - Kanał:
                    <span class="channel-badge">${channel}</span> ${sysIcon}
                    <button onclick="removePilot(${pilot.id})" style="width:auto; margin-left:10px; background-color:#dc3545;">
                        Usuń
                    </button>
                </li>`;
});


        groupHtml += '</ul></div>';
        container.innerHTML += groupHtml;
    });
}

// Konfiguracja WebSocketu
const wsProtocol = window.location.protocol === "https:" ? "wss://" : "ws://";
const ws = new WebSocket(wsProtocol + window.location.host + "/ws");

ws.onmessage = function(event) {
    const data = JSON.parse(event.data);

    // Aktualizacja timera i fazy na żywo
    if (data.type === "timer") {
        const phaseText = data.phase || "";
        const currentPhase = (document.getElementById("phaseDisplay").innerText || "").toLowerCase();

        document.getElementById("phaseDisplay").innerText = "Faza: " + data.phase;

        // Formatowanie sekund na MM:SS
        const minutes = Math.floor(data.time_left / 60);
        const seconds = data.time_left % 60;
        document.getElementById("timerDisplay").innerText =
            (minutes < 10 ? "0" : "") + minutes + ":" +
            (seconds < 10 ? "0" : "") + seconds;

        document.getElementById("currentGroupDisplay").innerText = "Leci grupa: " + data.group_id;

        // Znacznik "(Teraz leci)" opiera się o /api/groups.current_index,
        // więc odświeżamy grupy okresowo podczas tików timera.
        refreshGroupsThrottled();

        const phaseLower = (data.phase || "").toLowerCase();
        setPauseButton(phaseLower.includes("pauza"));

        updatePilotsDisplay();
    }

    // Ostrzeżenie 10 sekund przed końcem
    else if (data.type === "warning") {
        // Możesz tu w przyszłości dodać odtwarzanie dźwięku
        console.log("Ostrzeżenie: " + data.message);
    }

    // Automatyczne odświeżenie listy grup, gdy np. ktoś dołączy
    else if (data.type === "groups_updated") {
        fetchGroups();
    }
    else if (data.type === "flight_ended") {
        fetchGroups();
        updatePilotsDisplay();
    }
    else if (data.type === "phase_skipped") {
        fetchGroups();
    }
};

ws.onopen = function() {
    console.log("Połączono z serwerem WKM Racing!");
    setPauseButton(false);
    fetchGroups(); // Pobierz grupy przy pierwszym uruchomieniu
    updatePilotsDisplay();
};