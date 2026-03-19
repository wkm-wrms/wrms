
let lastGroupsFetchTs = 0;
let cachedGroups = { groups: [], current_index: 0 };

fetchGroups(); // Pobierz grupy przy pierwszym uruchomieniu

function updatePilotsDisplay() {
    const { groups, current_index } = cachedGroups;
    const next_index = (current_index + 1) % groups.length;

    console.log("Aktualizacja wyświetlania pilotów. Bieżące grupy:", groups, "Bieżący indeks:", current_index, "cachedGroups:", cachedGroups);
    document.getElementById('pilotR1').innerText = '';
    document.getElementById('pilotR3').innerText = '';
    document.getElementById('pilotR6').innerText = '';
    document.getElementById('pilotR7').innerText = '';
    document.getElementById('nextpilotR1').innerText = '';
    document.getElementById('nextpilotR3').innerText = '';
    document.getElementById('nextpilotR6').innerText = '';
    document.getElementById('nextpilotR7').innerText = '';

    if (!groups || groups.length === 0) {
        return;
    }

    // Bieżąca grupa
    pilotsbyId = {};
    currentchannels = {};
    nextchannels = {};

    groups[current_index].pilots.forEach(pilot => {
        pilotsbyId[pilot.id] = pilot;
        channel = groups[current_index].channels[pilot.id];
        currentchannels[channel] = pilot;
    });
    groups[next_index].pilots.forEach(pilot => {
        pilotsbyId[pilot.id] = pilot;
        channel = groups[next_index].channels[pilot.id];
        nextchannels[channel] = pilot;
    });

    document.getElementById('pilotR1').innerText = currentchannels["R1"] ? currentchannels["R1"]["name"] : '';
    document.getElementById('pilotR3').innerText = currentchannels["R3"] ? currentchannels["R3"]["name"] : '';
    document.getElementById('pilotR6').innerText = currentchannels["R6"] ? currentchannels["R6"]["name"] : '';
    document.getElementById('pilotR7').innerText = currentchannels["R7"] ? currentchannels["R7"]["name"] : '';
    document.getElementById('nextpilotR1').innerText = nextchannels["R1"] ? nextchannels["R1"]["name"] : '';
    document.getElementById('nextpilotR3').innerText = nextchannels["R3"] ? nextchannels["R3"]["name"] : '';
    document.getElementById('nextpilotR6').innerText = nextchannels["R6"] ? nextchannels["R6"]["name"] : '';
    document.getElementById('nextpilotR7').innerText = nextchannels["R7"] ? nextchannels["R7"]["name"] : '';

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



/*
// Konfiguracja WebSocketu
const wsProtocol = window.location.protocol === "https:" ? "wss://" : "ws://";
const ws = new WebSocket(wsProtocol + window.location.host + "/ws");

ws.onmessage = function (event) {
    const data = JSON.parse(event.data);
    console.log("Otrzymano wiadomość WebSocket:", data);
    handleServerMessage(data);
}

ws.onopen = function () {
    console.log("Połączono z serwerem WKM Racing!");
    setPauseButton(false);
    fetchGroups(); // Pobierz grupy przy pierwszym uruchomieniu
    updatePilotsDisplay();
};

*/

// Konfiguracja SSE (Server-Sent Events) jako fallback dla WebSocket

eventSource = new EventSource("/api/sse");
eventSource.onmessage = function (event) {
    const data = JSON.parse(event.data);
    handleServerMessage(data);
}

eventSource.onerror = function () {
    console.error("Błąd połączenia SSE. Próba ponownego połączenia...");
    setTimeout(() => {
        window.location.reload(); // Odśwież stronę, aby spróbować ponownie nawiązać połączenie
    }, 5000); // Spróbuj ponownie po 5 sekundach
};

async function handleServerMessage(data) {
    // Ta funkcja jest identyczna z ws.onmessage, ale obsługuje wiadomości z SSE
    // Aktualizacja timera i fazy na żywo
    if (data.type === "timer") {
        const phaseText = data.phase || "";
        const currentPhase = (document.getElementById("phaseDisplay").innerText || "").toLowerCase();

        document.getElementById("phaseDisplay").innerText = data.phase;

        // Formatowanie sekund na MM:SS
        const time_left = data.time_left || 0;
        const time_display = data.time_display || "00:00";

        const minutes = Math.floor(data.time_left / 60);
        const seconds = data.time_left % 60;
        document.getElementById("timerDisplay").innerText = time_display;

        document.getElementById("currentGroupDisplay").innerText = data.group_id;

        // Znacznik "(Teraz leci)" opiera się o /api/groups.current_index,
        // więc odświeżamy grupy okresowo podczas tików timera.
        // refreshGroupsThrottled();

        const phaseLower = (data.phase || "").toLowerCase();

        updatePilotsDisplay();
    }

    // Ostrzeżenie 10 sekund przed końcem
    else if (data.type === "warning") {
        // Możesz tu w przyszłości dodać odtwarzanie dźwięku
        console.log("Ostrzeżenie: " + data.message);
        const messageEl = document.getElementById("messageText");
        messageEl.innerText = data.message;
        messageEl.style.background_color = data.color || "black";
        messageEl.style.display = "block";
        messageEl.style.visibility = "visible";
        setTimeout(() => {
            messageEl.style.display = "none";
            messageEl.style.color = "black"; // Reset koloru po ukryciu
            messageEl.innerText = ""; // Reset tekstu po ukryciu
            messageEl.style.visibility = "hidden";
        }, (data.display_for || 5) * 1000); // Ukryj wiadomość po określonym czasie
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
