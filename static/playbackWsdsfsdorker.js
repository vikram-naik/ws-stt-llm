// playbackWorker.js
let chunkQueue = [], isProcessing = false;

async function processQueue() {
    if (isProcessing || !self.sourceBuffer || self.mediaSource.readyState !== 'open') {
        self.postMessage({ type: 'debug', message: 'Queue waiting: no sourceBuffer or processing' });
        return;
    }
    isProcessing = true;
    while (chunkQueue.length > 0) {
        if (self.sourceBuffer.updating) {
            self.postMessage({ type: 'debug', message: 'Waiting for updateend' });
            await new Promise(resolve => self.sourceBuffer.addEventListener('updateend', resolve, { once: true }));
        }
        const arrayBuffer = chunkQueue.shift();
        try {
            self.sourceBuffer.appendBuffer(arrayBuffer);
            self.postMessage({ type: 'appended', size: arrayBuffer.byteLength });
        } catch (e) {
            self.postMessage({ type: 'error', message: `Append failed: ${e.message}` });
        }
    }
    isProcessing = false;
}

self.onmessage = async (event) => {
    if (event.data.type === 'init') {
        self.postMessage({ type: 'debug', message: 'Worker initialized' });
    } else if (event.data.type === 'append') {
        const arrayBuffer = event.data.buffer;
        chunkQueue.push(arrayBuffer);
        self.postMessage({ type: 'queued', size: arrayBuffer.byteLength });
        self.postMessage({ type: 'debug', message: `Chunk queued: ${arrayBuffer.byteLength} bytes` });
        processQueue();
    } else if (event.data.type === 'end') {
        self.postMessage({ type: 'ended' });
        self.postMessage({ type: 'debug', message: 'Stream ended' });
    }
};

// Expose globals for main thread to set
self.mediaSource = null;
self.sourceBuffer = null;