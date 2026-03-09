let cachedGroups = { groups: [], current_index: 0 };

// Odtwarzanie dźwięków
function playStartSound() {
    const audio = document.getElementById('startSound');
    if (audio) {
        audio.currentTime = 0;
        audio.play().catch(err => console.log('Nie można odtworzyć dźwięku startu:', err));
    }
}

function playEndSound() {
    const audio = document.getElementById('endSound');
    if (audio) {
        audio.currentTime = 0;
        audio.play().catch(err => console.log('Nie można odtworzyć dźwięku końca:', err));
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

async function fetchGroups() {
    const response = await fetch('/api/groups');
    const data = await response.json();
    cachedGroups = data;
    updatePilotsDisplay();
}

// Konfiguracja WebSocketu
const wsProtocol = window.location.protocol === "https:" ? "wss://" : "ws://";
const ws = new WebSocket(wsProtocol + window.location.host + "/ws");

ws.onmessage = function(event) {
    const data = JSON.parse(event.data);

    if (data.type === "timer") {
        const phaseText = data.phase || "";
        const currentPhase = (document.getElementById("phaseDisplay").innerText || "").toLowerCase();

        document.getElementById("phaseDisplay").innerText = "Faza: " + data.phase;

        // Odtwarzaj dźwięk startu przy przejściu do FLIGHT
        if (phaseText.toLowerCase().includes("przelot") && !currentPhase.includes("przelot")) {
            playStartSound();
        }

        const minutes = Math.floor(data.time_left / 60);
        const seconds = data.time_left % 60;
        document.getElementById("timerDisplay").innerText =
            (minutes < 10 ? "0" : "") + minutes + ":" +
            (seconds < 10 ? "0" : "") + seconds;

        document.getElementById("currentGroupDisplay").innerText = "Leci grupa: " + data.group_id;

        fetchGroupsForDisplay();
    }
    else if (data.type === "groups_updated") {
        fetchGroups();
    }
    else if (data.type === "flight_ended") {
        playEndSound();
        fetchGroups();
    }
    else if (data.type === "session_paused") {
        document.getElementById("phaseDisplay").innerText = "Faza: Oczekiwanie / Pauza";
    }
    else if (data.type === "session_resumed") {
        fetchGroups();
    }
    else if (data.type === "phase_skipped") {
        fetchGroups();
    }
};

ws.onopen = function() {
    console.log("Połączono z wyświetlaczem WKM Racing!");
    fetchGroups();
    updatePilotsDisplay();
};

