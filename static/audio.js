const host = location.hostname || 'localhost';
let socket, udpSocket, transcribeSocket, recorder, audioElement, audioContext;
let audioChunks = [];
let currentCall = { group: null, username: null, call_id: null, peer: null, language: null, transcripts: { sales: [], customers: [] } };
const ringtone = new Audio('/static/ringtone.mp3');
ringtone.loop = true;
const ringback = new Audio('/static/ringback.mp3');
ringback.loop = true;

const DEBUG = false;

let mediaSource, sourceBuffer, chunkQueue = [], isProcessing = false;

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
    if (DEBUG) console.log('Main thread: SourceBuffer ready');

    const osLanguage = navigator.language.split('-')[0];
    const supportedLanguages = ['en', 'ja'];
    document.getElementById('language').value = supportedLanguages.includes(osLanguage) ? osLanguage : 'en';

    socket.onopen = () => { if (DEBUG) console.log('Connected to signaling server'); };
    udpSocket.onopen = () => {
        if (DEBUG) console.log('UDP relay WebSocket opened');
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
        if (DEBUG) console.log('Transcription WebSocket opened');
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
        try {
            const data = JSON.parse(event.data);
            if (DEBUG) console.log('Received from signaling:', data);
            switch (data.event) {
                case 'set_cookie':
                    document.cookie = `session_id=${data.session_id}; path=/`;
                    break;
                case 'user_status':
                    updateUserList(data);
                    break;
                case 'incoming_call':
                    currentCall.peer = { user: data.from_user };
                    currentCall.call_id = data.call_id;
                    ringtone.play().catch(e => console.error('Ringtone error:', e));
                    showIncomingCall(data.from_user, data.call_id);
                    break;
                case 'call_accepted':
                    currentCall.peer = { user: data.from_user };
                    ringback.pause();
                    ringback.currentTime = 0;
                    startAudioStream();
                    callAccepted();
                    break;
                case 'call_ended':
                    ringtone.pause();
                    ringtone.currentTime = 0;
                    ringback.pause();
                    ringback.currentTime = 0;
                    await endCall();
                    callEnded();
                    break;
                case 'call_rejected':
                    rejectCall();
                    break;
                case 'error':
                    console.error('Server error:', data.message);
                    showError(data.message);
                    break;
            }
        } catch (error) {
            console.error('Error in socket.onmessage:', error);
        }
    };
    
    window.callUser = async function(to_user) {
        if (currentCall.call_id) return showError('Already in a call');
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
        updateUserList({ sales: window.sales, customers: window.customers });
    };
    
    window.hangUp = async function() {
        ringback.pause();
        ringback.currentTime = 0;
        ringtone.pause();
        ringtone.currentTime = 0;
        if (currentCall.call_id) {
            socket.send(JSON.stringify({
                event: 'hang_up',
                call_id: currentCall.call_id
            }));
            await endCall();
            callEnded();
        }
    };
    
    window.acceptCall = async function() {
        ringtone.pause();
        ringtone.currentTime = 0;
        socket.send(JSON.stringify({
            event: 'accept_call',
            from_group: currentCall.peer.group,
            from_user: currentCall.peer.user,
            to_user: currentCall.username,
            call_id: currentCall.call_id
        }));
        startAudioStream();
        callAccepted();
    };
    
    window.rejectCall = async function() {
        try{
            ringtone.pause();
            ringtone.currentTime = 0;
            ringback.pause();
            ringback.currentTime = 0;
            socket.send(JSON.stringify({
                event: 'call_rejected',
                from_group: currentCall.peer.group,
                from_user: currentCall.peer.user,
                to_user: currentCall.username,
                call_id: currentCall.call_id
            }));
            await endCall();
            callEnded();    
        }catch(error){
            console.error('Error starting audio stream:', e.name, e.message);
        }
    };
    

    udpSocket.onmessage = async (event) => {
        if (event.data instanceof Blob) {
            const arrayBuffer = await event.data.arrayBuffer();
            chunkQueue.push(arrayBuffer);
            if (DEBUG) console.log('Queued WebM Opus chunk:', arrayBuffer.byteLength);
            processQueue();
        }
    };

    transcribeSocket.onmessage = async (event) => {
        const data = JSON.parse(event.data);
        if (currentCall.group === 'sales' && currentCall.call_id === data.call_id) {
            if (data.event === 'transcription') {
                console.log('Transcription received:', data);
                if (!data.is_final) {
                    updatePartial(data.text, data.group); // Direct call
                } else {
                    currentCall.transcripts[data.group === 'sales' ? 'sales' : 'customers'].push(data.text);
                    addFinal(data.text, data.group); // Direct call
                }
            } else if (data.event === 'insight') {
                addInsight(data.text); // Direct call
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

async function endCall() {
    if (DEBUG) console.log('Ending call');
    if (recorder && recorder.state !== 'inactive') {
        recorder.stop();
    }
    if (audioContext.state !== 'closed') {
        await audioContext.close();
    }
    recorder = null;
    audioContext = new AudioContext({ sampleRate: 16000 });
    if (mediaSource.readyState === 'open') {
        mediaSource.endOfStream();
    }
    if (transcribeSocket.readyState === WebSocket.OPEN && currentCall.call_id) {
        transcribeSocket.send(JSON.stringify({
            event: 'call_ended',
            call_id: currentCall.call_id
        }));
        if (DEBUG) console.log('Sent call_ended to transcription server');
    }
    mediaSource = new MediaSource();
    audioElement.src = URL.createObjectURL(mediaSource);
    await new Promise(resolve => mediaSource.addEventListener('sourceopen', resolve, { once: true }));
    sourceBuffer = mediaSource.addSourceBuffer('audio/webm;codecs=opus');
    sourceBuffer.mode = 'sequence';
    chunkQueue = [];
    isProcessing = false;
    currentCall.call_id = null;
    currentCall.peer = null;
    // No DOM updates here—handled by ui.js
}

function processQueue() {
    if (isProcessing || !sourceBuffer || mediaSource.readyState !== 'open') {
        if (DEBUG) console.log('Queue waiting: processing or not ready');
        return;
    }
    isProcessing = true;
    const appendNext = () => {
        if (chunkQueue.length === 0) {
            isProcessing = false;
            return;
        }
        if (sourceBuffer.updating) {
            sourceBuffer.addEventListener('updateend', appendNext, { once: true });
            return;
        }
        const arrayBuffer = chunkQueue.shift();
        try {
            sourceBuffer.appendBuffer(arrayBuffer);
            if (DEBUG) console.log('Appended WebM Opus chunk:', arrayBuffer.byteLength);
            appendNext();
        } catch (e) {
            console.error('Append error:', e.message);
            isProcessing = false;
        }
    };
    appendNext();
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
    showMainUI(group);
}

async function startAudioStream() {
    let stream;
    try {
        const stream = await navigator.mediaDevices.getUserMedia({
            audio: {
                sampleRate: 16000,
                noiseSuppression: true,
                echoCancellation: true,
                autoGainControl: true
            }
        });
        console.log('Microphone access granted, stream:', stream);
        const sourceNode = audioContext.createMediaStreamSource(stream);
        console.log('Input stream sample rate:', stream.getAudioTracks()[0].getSettings().sampleRate);
        console.log('AudioContext sample rate:', audioContext.sampleRate);

        recorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
        recorder.ondataavailable = (event) => {
            if (event.data.size > 0 && udpSocket.readyState === WebSocket.OPEN) {
                udpSocket.send(event.data);
                if (DEBUG) console.log('Sent WebM Opus packet to relay:', event.data.size);
            }
        };
        recorder.onstop = () => {
            stream.getTracks().forEach(track => track.stop());
        };
        recorder.start(20);

        await audioContext.audioWorklet.addModule('/static/audioWorklet.js');
        const pcmNode = new AudioWorkletNode(audioContext, 'pcm-processor', {
            processorOptions: { bufferSize: 1024 }
        });
        pcmNode.port.onmessage = (event) => {
            const pcmBlob = new Blob([event.data], { type: 'audio/pcm' });
            if (DEBUG) console.log('PCM chunk, first 10 samples:', event.data.slice(0, 10));
            if (transcribeSocket.readyState === WebSocket.OPEN) {
                transcribeSocket.send(pcmBlob);
                if (DEBUG) console.log('Sent PCM packet for transcription (sales only):', pcmBlob.size);
            }
        };
        sourceNode.connect(pcmNode);
        pcmNode.connect(audioContext.destination);

        if (DEBUG) console.log('MediaRecorder and PCM processing started successfully');
        if (currentCall.group === 'sales') document.getElementById('transcription').classList.remove('d-none');
    } catch (e) {
        console.error('Error starting audio stream:', e.name, e.message);
        alert('Failed to access microphone. Please allow permissions and try again.');
        await endCall();
    }
}

initAudio();