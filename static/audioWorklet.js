class PCMProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
    }

    process(inputs, outputs) {
        const input = inputs[0][0]; // First channel input
        const int16Data = new Int16Array(input.length);

        for (let i = 0; i < input.length; i++) {
            // Apply 2x gain
            let sample = input[i] * 32767 * 2;
            int16Data[i] = Math.max(-32768, Math.min(32767, Math.round(sample)));
        }

        // Send PCM data
        this.port.postMessage(int16Data);

        return true;
    }
}

registerProcessor('pcm-processor', PCMProcessor);