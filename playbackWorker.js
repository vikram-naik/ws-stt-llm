// playbackWorker.js
let mediaSource, sourceBuffer;

self.onmessage = async (event) => {
    if (event.data.type === 'init') {
        mediaSource = new MediaSource();
        self.postMessage({ type: 'url', url: URL.createObjectURL(mediaSource) });
        mediaSource.addEventListener('sourceopen', () => {
            sourceBuffer = mediaSource.addSourceBuffer('audio/webm;codecs=opus');
            sourceBuffer.mode = 'sequence';
            self.postMessage({ type: 'ready' });
        }, { once: true });
    } else if (event.data.type === 'append') {
        const arrayBuffer = event.data.buffer;
        if (sourceBuffer && !sourceBuffer.updating && mediaSource.readyState === 'open') {
            try {
                sourceBuffer.appendBuffer(arrayBuffer);
            } catch (e) {
                self.postMessage({ type: 'error', message: e.message });
            }
        }
    } else if (event.data.type === 'end') {
        if (mediaSource.readyState === 'open') {
            mediaSource.endOfStream();
        }
    }
};