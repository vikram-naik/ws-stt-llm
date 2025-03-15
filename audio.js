const host = location.hostname || 'localhost';
let socket, udpSocket, transcribeSocket, recorder, audioElement, audioContext, sourceNode, processorNode;
let audioChunks = [];
let currentCall = { group: null, username: null, call_id: null, peer: null, language: null, transcripts: { sales: [], customers: [] } };
const ringtone = new Audio('/static/ringtone.mp3');
ringtone.loop = true;
const ringback = new Audio('/static/ringback.mp3');
ringback.loop = true;

let mediaSource, sourceBuffer;

async function initAudio() {
    socket = new WebSocket(`wss://${host}:8001`, [], { pingInterval: 30000 });
    udpSocket = new WebSocket(`wss://${host}:8002`, [], { pingInterval: 30000 });
    transcribeSocket = new WebSocket(`wss://${host}:8003`, [], { pingInterval: 30000 });
    audioElement = document.createElement('audio');
    audioElement.autoplay = true;
    document.body.appendChild(audioElement);
    audioContext = new AudioContext({ sampleRate: 16000 });

    mediaSource = new MediaSource();
    audioElement.src = URL.createObjectURL(mediaSource);
    await new Promise(resolve => mediaSource.addEventListener('sourceopen', resolve, { once: true }));
    sourceBuffer = mediaSource.addSourceBuffer('audio/webm;codecs=opus');
    sourceBuffer.mode = 'sequence';
    console.log('MediaSource initialized');

    const osLanguage = navigator.language.split('-')[0];
    const supportedLanguages = ['en', 'ja'];
    document.getElementById('language').value = supportedLanguages.includes(osLanguage) ? osLanguage : 'en';

    socket.onopen = () => console.log('Connected to signaling server');
    udpSocket.onopen = () => {
        console.log('UDP relay WebSocket opened');
        if (currentCall.group && currentCall.username) {
            udpSocket.send(JSON.stringify({
                event: 'register',
                group: currentCall.group,
                username: currentCall.username,
                language: currentCall.language
            }));
        }
    };
    transcribeSocket.onopen = () => {
        console.log('Transcription WebSocket opened');
        if (currentCall.group && currentCall.username) {
            transcribeSocket.send(JSON.stringify({
                event: 'register',
                group: currentCall.group,
                username: currentCall.username,
                language: currentCall.language
            }));
        }
    };

    socket.onmessage = async (event) => {
        const data = JSON.parse(event.data);
        console.log('Received from signaling:', data);
        switch (data.event) {
            case 'set_cookie':
                document.cookie = `session_id=${data.session_id}; path=/`;
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
                await endCall();
                break;
            case 'error':
                console.error('Server error:', data.message);
                alert(data.message);
                break;
        }
    };

    udpSocket.onmessage = async (event) => {
        if (event.data instanceof Blob) {
            audioChunks.push(event.data);
            if (!isProcessing) processAudioQueue();
        }
    };

    transcribeSocket.onmessage = async (event) => {
        const data = JSON.parse(event.data);
        if (currentCall.group === 'sales' && currentCall.call_id === data.call_id) {
            if (data.event === 'transcription') {
                const targetPartial = data.group === 'sales' ? 'sales-partial' : 'customer-partial';
                const targetFinals = data.group === 'sales' ? 'sales-finals' : 'customer-finals';
                if (!data.is_final) {
                    document.getElementById(targetPartial).value = data.text; // Update textbox
                } else {
                    document.getElementById(targetPartial).value = ''; // Clear textbox
                    const p = document.createElement('p');
                    p.textContent = data.text;
                    document.getElementById(targetFinals).appendChild(p); // Append as paragraph
                    document.getElementById(targetFinals).scrollTop = document.getElementById(targetFinals).scrollHeight; // Auto-scroll
                    currentCall.transcripts[data.group === 'sales' ? 'sales' : 'customers'].push(data.text);
                }
                document.getElementById('transcription').classList.remove('d-none');
            } else if (data.event === 'insight') {
                const insightDiv = document.getElementById('insights');
                const p = document.createElement('p');
                p.textContent = data.text;
                insightDiv.appendChild(p);
                insightDiv.scrollTop = insightDiv.scrollHeight;
            }
        }
    };

    socket.onclose = async () => {
        console.warn('Signaling WebSocket closed—reconnecting');
        socket = new WebSocket(`wss://${host}:8001`, [], { pingInterval: 30000 });
        await new Promise(resolve => socket.onopen = resolve);
        if (currentCall.username) register(currentCall.group, currentCall.username);
    };
    udpSocket.onclose = async () => {
        console.warn('UDP relay WebSocket closed—reconnecting');
        udpSocket = new WebSocket(`wss://${host}:8002`, [], { pingInterval: 30000 });
        await new Promise(resolve => udpSocket.onopen = resolve);
    };
    transcribeSocket.onclose = async () => {
        console.warn('Transcription WebSocket closed—reconnecting');
        transcribeSocket = new WebSocket(`wss://${host}:8003`, [], { pingInterval: 30000 });
        await new Promise(resolve => transcribeSocket.onopen = resolve);
    };
}

let isProcessing = false;

async function processAudioQueue() {
    if (isProcessing || !sourceBuffer || mediaSource.readyState !== 'open') {
        console.log('Skipping processAudioQueue: not ready');
        return;
    }
    isProcessing = true;
    while (audioChunks.length > 0) {
        if (sourceBuffer.updating) {
            await new Promise(resolve => sourceBuffer.addEventListener('updateend', resolve, { once: true }));
        }
        const chunk = audioChunks.shift();
        const arrayBuffer = await chunk.arrayBuffer();
        try {
            sourceBuffer.appendBuffer(arrayBuffer);
            console.log('Appended WebM Opus chunk:', arrayBuffer.byteLength);
        } catch (e) {
            console.error('AppendBuffer error:', e);
        }
        await new Promise(resolve => setTimeout(resolve, 20));
    }
    isProcessing = false;
}

function register(group = null, username = null) {
    group = group || document.querySelector('input[name="group"]:checked').value;
    username = username || document.getElementById('username').value;
    const language = document.getElementById('language').value;
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
            username: username,
            language: language
        }));
    }
    if (transcribeSocket.readyState === WebSocket.OPEN) {
        transcribeSocket.send(JSON.stringify({
            event: 'register',
            group: group,
            username: username,
            language: language
        }));
    }
    currentCall.group = group;
    currentCall.username = username;
    currentCall.language = language;
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
    // Reset transcription UI for new call
    document.getElementById('sales-finals').innerHTML = '';
    document.getElementById('customer-finals').innerHTML = '';
    document.getElementById('sales-partial').value = '';
    document.getElementById('customer-partial').value = '';
    document.getElementById('insights').innerHTML = '';
    document.getElementById('transcription').classList.add('d-none');
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
    // Reset transcription UI for new call
    document.getElementById('sales-finals').innerHTML = '';
    document.getElementById('customer-finals').innerHTML = '';
    document.getElementById('sales-partial').value = '';
    document.getElementById('customer-partial').value = '';
    document.getElementById('insights').innerHTML = '';
    document.getElementById('transcription').classList.add('d-none');
    showCallControls();
    startAudioStream();
}

async function rejectCall() {
    ringtone.pause();
    ringtone.currentTime = 0;
    document.getElementById('incoming-call').classList.add('d-none');
    socket.send(JSON.stringify({
        event: 'call_rejected',
        from_group: currentCall.peer.group,
        from_user: currentCall.peer.user,
        to_user: currentCall.username
    }));
    await endCall();
}

async function hangUp() {
    ringback.pause();
    ringback.currentTime = 0;
    if (currentCall.call_id) {
        socket.send(JSON.stringify({
            event: 'hang_up',
            call_id: currentCall.call_id
        }));
        await endCall();
    }
}

async function endCall() {
    console.log('Ending call');
    if (recorder && recorder.state !== 'inactive') {
        recorder.stop();
    }
    if (sourceNode) sourceNode.disconnect();
    if (processorNode) processorNode.disconnect();
    recorder = null;
    sourceNode = null;
    processorNode = null;
    audioChunks = [];
    if (mediaSource.readyState === 'open') {
        mediaSource.endOfStream();
    }
    mediaSource = new MediaSource();
    audioElement.src = URL.createObjectURL(mediaSource);
    await new Promise(resolve => mediaSource.addEventListener('sourceopen', resolve, { once: true }));
    sourceBuffer = mediaSource.addSourceBuffer('audio/webm;codecs=opus');
    sourceBuffer.mode = 'sequence';
    console.log('MediaSource reset');
    document.getElementById('call-controls').classList.add('d-none');
    // Keep transcription UI visible until new call
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
    let stream;
    try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        console.log('Microphone access granted, stream:', stream);

        recorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
        recorder.ondataavailable = (event) => {
            if (event.data.size > 0 && udpSocket.readyState === WebSocket.OPEN) {
                udpSocket.send(event.data);
                console.log('Sent WebM Opus packet to relay:', event.data.size);
            }
        };
        recorder.onstop = () => {
            stream.getTracks().forEach(track => track.stop());
        };
        recorder.start(20);

        sourceNode = audioContext.createMediaStreamSource(stream);
        processorNode = audioContext.createScriptProcessor(1024, 1, 1);
        processorNode.onaudioprocess = (event) => {
            const floatData = event.inputBuffer.getChannelData(0);
            const int16Data = new Int16Array(floatData.length);
            for (let i = 0; i < floatData.length; i++) {
                int16Data[i] = Math.max(-32768, Math.min(32767, floatData[i] * 32768));
            }
            const pcmBlob = new Blob([int16Data.buffer], { type: 'audio/pcm' });
            if (transcribeSocket.readyState === WebSocket.OPEN) {
                transcribeSocket.send(pcmBlob);
                console.log('Sent PCM packet for transcription:', pcmBlob.size);
            }
        };
        sourceNode.connect(processorNode);
        processorNode.connect(audioContext.destination);

        console.log('MediaRecorder and PCM processing started successfully');
        if (currentCall.group === 'sales') document.getElementById('transcription').classList.remove('d-none');
    } catch (e) {
        console.error('Error starting audio stream:', e.name, e.message);
        alert('Failed to access microphone. Please allow permissions and try again.');
        await endCall();
    }
}

initAudio();