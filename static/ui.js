// Set default language based on OS locale
const userLang = navigator.language.split('-')[0];
const langSelect = document.getElementById('language');
if (userLang === 'en' || userLang === 'ja') {
    langSelect.value = userLang;
} else {
    langSelect.value = 'en';
}

// Entry form submission
document.getElementById('entryForm').addEventListener('submit', (e) => {
    e.preventDefault();
    const group = document.querySelector('input[name="group"]:checked').value;
    const username = document.getElementById('username').value;
    // Language is fetched by register() directly from #language
    register(group, username); // Call audio.js's register function
});

// Logout (adjusted for new IDs)
document.getElementById('logoutBtn').addEventListener('click', () => {
    document.getElementById('mainUI').classList.add('d-none');
    document.getElementById('entryScreen').classList.remove('d-none');
    document.getElementById('transcription').classList.add('d-none');
    document.getElementById('logoutBtn').classList.add('d-none');
});

// UI updates (placeholders for WebSocket events)
function updatePartial(text) {
    document.getElementById('partial-bubble').innerHTML = text;
}

function addFinal(text, group) {
    const finals = document.getElementById('finals');
    const bubble = document.createElement('div');
    bubble.className = `chat-bubble-${group}`;
    bubble.innerHTML = text;
    finals.appendChild(bubble);
}

function showIncomingCall(caller) {
    document.getElementById('callerText').innerHTML = `${caller} is calling...`;
    new bootstrap.Modal(document.getElementById('incomingCall')).show();
}