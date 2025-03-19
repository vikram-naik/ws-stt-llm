class PCMProcessor extends AudioWorkletProcessor {
    constructor(options) {
        super();
        this.bufferSize = options.processorOptions.bufferSize || 1024;
        this.buffer = new Float32Array(this.bufferSize);
        this.pos = 0;
    }

    process(inputs, outputs) {
        const input = inputs[0][0]; // First channel, Float32
        if (!input) return true;        
        for (let i = 0; i < input.length; i++) {
            this.buffer[this.pos++] = input[i];
            if (this.pos === this.bufferSize) {
                // Convert to Int16 for Vosk
                const int16Data = new Int16Array(this.bufferSize);
                let maxSample = 0;
                for (let j = 0; j < this.bufferSize; j++) {
                    maxSample = Math.max(maxSample, Math.abs(this.buffer[j]));
                }
                const gainFactor = maxSample > 0 ? Math.min(2, 0.9 / maxSample) : 1;
                for (let j = 0; j < this.bufferSize; j++) {
                    let sample = this.buffer[j] * 32767 * gainFactor;
                    int16Data[j] = Math.max(-32768, Math.min(32767, Math.round(sample)));
                }
                this.port.postMessage(int16Data);
                this.pos = 0;
            }
        }
        return true;
    }
}

registerProcessor('pcm-processor', PCMProcessor);