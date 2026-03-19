// Panel administratora WKM Racing Management System
// Ten skrypt obsługuje interakcje na stronie admina, w tym zarządzanie sesją,
// dodawanie pilotów, aktualizację wyświetlacza i komunikację z serwerem przez WebSocket lub SSE.   
// Rozpoczęcie sesji


async function searchPilots() {
    const query = document.getElementById('pilotSearchInput').value.trim();
    if (!query) {
        document.getElementById('searchResults').innerHTML = '';
        return;
    }

    try {
        const response = await fetch(`/api/pilots/${query}`);
        const result = await response.json();

        if (response.ok) {
            displaySearchResults(result);
        } else {
            console.error("Search failed:", result.detail);
        }
    } catch (error) {
        console.error("Search error:", error);
    }
}

function displaySearchResults(pilots) {
    const resultsContainer = document.getElementById('searchResults');
    if (!Array.isArray(pilots) || pilots.length === 0) {
        resultsContainer.innerHTML = '<p>Brak wyników</p>';
        return;
    }

    const html = pilots.map(pilot => `
        <div class="pilot-result">
            <span>${pilot.name}</span>
            <span>${pilot.digital ? 'Digital' : 'Analog'}</span>
        </div>
    `).join('');

    resultsContainer.innerHTML = html;
}


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
    if (response.ok) {
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

function refreshGroupsThrottled(minIntervalMs = 1200) {
    const now = Date.now();
    if (now - lastGroupsFetchTs >= minIntervalMs) {
        lastGroupsFetchTs = now;
        fetchGroups();
    }
}
