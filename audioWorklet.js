// audioWorklet.js
class PCMProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        this.bufferSize = 1024; // ~64ms at 16kHz
    }

    process(inputs) {
        const input = inputs[0];
        if (input.length > 0) {
            const floatData = input[0]; // Mono channel
            const int16Data = new Int16Array(floatData.length);
            for (let i = 0; i < floatData.length; i++) {
                int16Data[i] = Math.max(-32768, Math.min(32767, floatData[i] * 32768));
            }
            this.port.postMessage(int16Data.buffer, [int16Data.buffer]);
        }
        return true; // Keep processor alive
    }
}

registerProcessor('pcm-processor', PCMProcessor);