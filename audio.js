const host = location.hostname || 'localhost';
let socket, udpSocket, mediaRecorder, mediaSource, sourceBuffer;
let audioChunks = [];
let currentCall = { group: null, username: null, call_id: null, peer: null };
const ringtone = new Audio('/static/ringtone.mp3');
ringtone.loop = true;
const ringback = new Audio('/static/ringback.mp3');
ringback.loop = true;
let audioElement;

async function initAudio() {
    socket = new WebSocket(`wss://${host}:8001`);
    udpSocket = new WebSocket(`wss://${host}:8002`);
    audioElement = document.createElement('audio');
    audioElement.autoplay = true;
    document.body.appendChild(audioElement);
    resetMediaSource();

    socket.onopen = () => console.log('Connected to signaling server');
    udpSocket.onopen = () => {
        console.log('UDP relay WebSocket opened');
        if (currentCall.group && currentCall.username) {
            udpSocket.send(JSON.stringify({
                event: 'register',
                group: currentCall.group,
                username: currentCall.username
            }));
        }
    };

    socket.onmessage = async (event) => {
        const data = JSON.parse(event.data);
        console.log('Received from signaling:', data);
        switch (data.event) {
            case 'set_cookie':
                document.cookie = `session_id=${data.session_id}; path=/`;
                console.log('Session ID set');
                break;
            case 'user_status':
                document.getElementById('sales-list').dataset.users = data.sales.join(',');
                document.getElementById('customers-list').dataset.users = data.customers.join(',');
                updateUserList('sales-list', data.sales);
                updateUserList('customers-list', data.customers);
                break;
            case 'incoming_call':
                currentCall.peer = { user: data.from_user };
                currentCall.call_id = data.call_id;
                document.getElementById('caller').textContent = data.from_user;
                ringtone.play().catch(e => console.error('Ringtone error:', e));
                document.getElementById('incoming-call').classList.remove('d-none');
                break;
            case 'call_accepted':
                currentCall.peer = { user: data.from_user };
                ringback.pause();
                ringback.currentTime = 0;
                startAudioStream();
                break;
            case 'call_ended':
                endCall();
                break;
            case 'error':
                console.error('Server error:', data.message);
                alert(data.message);
                break;
        }
    };

    udpSocket.onmessage = async (event) => {
        if (event.data instanceof Blob) {
            console.log('Audio data received:', event.data.size);
            audioChunks.push(event.data);
            console.log('Queue length:', audioChunks.length);
            if (!isProcessing) processAudioQueue();
        } else {
            const data = JSON.parse(event.data);
            console.log('Received from UDP relay:', data);
            if (data.event === 'transcription' && currentCall.group === 'sales' && currentCall.call_id === data.call_id) {
                const target = data.group === 'sales' ? 'sales-transcription' : 'customer-transcription';
                const currentText = document.getElementById(target).textContent;
                document.getElementById(target).textContent = `${currentText}\n${data.text}`.trim();
                document.getElementById('transcription').classList.remove('d-none');
            }
        }
    };

    socket.onclose = async () => {
        console.log('Signaling WebSocket closed—reconnecting');
        socket = new WebSocket(`wss://${host}:8001`);
        await new Promise(resolve => socket.onopen = resolve);
        if (currentCall.username) register(currentCall.group, currentCall.username);
    };
    udpSocket.onclose = async () => {
        console.log('UDP relay WebSocket closed—reconnecting');
        udpSocket = new WebSocket(`wss://${host}:8002`);
        await new Promise(resolve => udpSocket.onopen = resolve);
    };
}

function resetMediaSource() {
    mediaSource = new MediaSource();
    audioElement.src = URL.createObjectURL(mediaSource);
    mediaSource.addEventListener('sourceopen', () => {
        sourceBuffer = mediaSource.addSourceBuffer('audio/webm;codecs=opus');
        sourceBuffer.mode = 'sequence';
        console.log('MediaSource reset and SourceBuffer ready');
    });
}

let isProcessing = false;

async function processAudioQueue() {
    if (isProcessing) return;
    isProcessing = true;
    while (mediaSource.readyState === 'open' && audioChunks.length > 0) {
        if (!sourceBuffer.updating) {
            const chunk = audioChunks.shift();
            try {
                sourceBuffer.appendBuffer(await chunk.arrayBuffer());
                console.log('Appended audio chunk:', chunk.size);
            } catch (e) {
                console.error('AppendBuffer error:', e);
            }
        }
        await new Promise(resolve => setTimeout(resolve, 5));
    }
    isProcessing = false;
}

function register(group = null, username = null) {
    group = group || document.getElementById('group').value;
    username = username || document.getElementById('username').value;
    if (!group || !username) {
        alert('Please enter group and username');
        return;
    }
    socket.send(JSON.stringify({
        event: 'register',
        group: group,
        username: username
    }));
    if (udpSocket.readyState === WebSocket.OPEN) {
        udpSocket.send(JSON.stringify({
            event: 'register',
            group: group,
            username: username
        }));
    }
    currentCall.group = group;
    currentCall.username = username;
    document.getElementById('login').classList.add('d-none');
    document.getElementById('main').classList.remove('d-none');
    if (group === 'sales') document.getElementById('transcription').classList.remove('d-none');
    showLogoutButton();
}

async function callUser(to_user) {
    if (currentCall.call_id) return alert('Already in a call');
    currentCall.call_id = `call_${Date.now()}_${currentCall.username}`;
    currentCall.peer = { group: currentCall.group === 'sales' ? 'customers' : 'sales', user: to_user };
    socket.send(JSON.stringify({
        event: 'call_user',
        from_group: currentCall.group,
        from_user: currentCall.username,
        to_user: to_user,
        call_id: currentCall.call_id
    }));
    ringback.play().catch(e => console.error('Ringback error:', e));
    showCallControls();
}

async function acceptCall() {
    ringtone.pause();
    ringtone.currentTime = 0;
    document.getElementById('incoming-call').classList.add('d-none');
    socket.send(JSON.stringify({
        event: 'accept_call',
        call_id: currentCall.call_id,
        from_group: currentCall.peer.group,
        from_user: currentCall.peer.user,
        to_user: currentCall.username
    }));
    showCallControls();
    startAudioStream();
}

function rejectCall() {
    ringtone.pause();
    ringtone.currentTime = 0;
    document.getElementById('incoming-call').classList.add('d-none');
    socket.send(JSON.stringify({
        event: 'call_rejected',
        from_group: currentCall.peer.group,
        from_user: currentCall.peer.user,
        to_user: currentCall.username
    }));
    endCall();
}

function hangUp() {
    ringback.pause();
    ringback.currentTime = 0;
    if (currentCall.call_id) {
        socket.send(JSON.stringify({
            event: 'hang_up',
            call_id: currentCall.call_id
        }));
        endCall();
    }
}

function endCall() {
    console.log('Ending call');
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop();
        mediaRecorder.stream.getTracks().forEach(track => track.stop());
    }
    mediaRecorder = null;
    audioChunks = [];
    resetMediaSource();
    document.getElementById('call-controls').classList.add('d-none');
    if (currentCall.group === 'sales') {
        document.getElementById('sales-transcription').textContent = '';
        document.getElementById('customer-transcription').textContent = '';
        document.getElementById('transcription').classList.add('d-none');
    }
    currentCall.call_id = null;
    currentCall.peer = null;
    updateUserList('sales-list', document.getElementById('sales-list').dataset.users?.split(',') || []);
    updateUserList('customers-list', document.getElementById('customers-list').dataset.users?.split(',') || []);
}

function showCallControls() {
    document.getElementById('call-controls').classList.remove('d-none');
}

function updateUserList(elementId, users) {
    const list = document.getElementById(elementId);
    list.innerHTML = '';
    const isSales = currentCall.group === 'sales';
    const targetGroup = elementId === 'sales-list' ? 'sales' : 'customers';
    const inCall = !!currentCall.call_id;

    users.forEach(user => {
        const li = document.createElement('li');
        li.className = 'list-group-item d-flex justify-content-between align-items-center';
        li.textContent = user;
        if ((isSales && targetGroup === 'customers') || (!isSales && targetGroup === 'sales')) {
            const callBtn = document.createElement('button');
            callBtn.className = 'btn btn-primary btn-sm';
            callBtn.textContent = 'Call';
            callBtn.onclick = () => callUser(user);
            callBtn.disabled = inCall;
            li.appendChild(callBtn);
        }
        list.appendChild(li);
    });
}

function showLogoutButton() {
    if (!document.getElementById('logout-btn')) {
        const logoutBtn = document.createElement('button');
        logoutBtn.id = 'logout-btn';
        logoutBtn.className = 'btn btn-danger mt-3';
        logoutBtn.textContent = 'Logout';
        logoutBtn.onclick = () => {
            socket.send(JSON.stringify({ event: 'logout', username: currentCall.username }));
            document.cookie = 'session_id=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
            window.location.reload();
        };
        document.getElementById('main').appendChild(logoutBtn);
    }
}

async function startAudioStream() {
    try {
        audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(audioStream, { mimeType: 'audio/webm;codecs=opus' });
        mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0 && udpSocket.readyState === WebSocket.OPEN) {
                console.log('Sending audio chunk:', event.data.size, event.data.type);
                udpSocket.send(event.data);
            }
        };
        mediaRecorder.onstop = () => {
            audioStream.getTracks().forEach(track => track.stop());
        };
        mediaRecorder.start(100);
        console.log('Audio stream started');
        if (currentCall.group === 'sales') document.getElementById('transcription').classList.remove('d-none');
    } catch (e) {
        console.error('Error starting audio stream:', e);
        alert('Failed to access microphone. Please allow permissions and try again.');
        endCall();
    }
}

initAudio();