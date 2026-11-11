/**
 * Microphone capture worklet.
 * Downsamples the mic stream from the device rate (usually 48 kHz) to 16 kHz,
 * converts to 16-bit PCM and posts ~32 ms chunks to the main thread.
 * A box filter over each output window doubles as a simple anti-aliasing filter.
 */
const TARGET_RATE = 16000;
const CHUNK_SAMPLES = 512; // 32 ms at 16 kHz

class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / TARGET_RATE;
    this.pending = new Float32Array(8192);
    this.pendingLen = 0;
    this.readPos = 0;
    this.out = new Int16Array(CHUNK_SAMPLES);
    this.outLen = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;

    if (this.pendingLen + channel.length > this.pending.length) {
      // Should never happen (we drain every call), but never overflow.
      this.pendingLen = 0;
      this.readPos = 0;
    }
    this.pending.set(channel, this.pendingLen);
    this.pendingLen += channel.length;

    while (this.readPos + this.ratio <= this.pendingLen) {
      const start = Math.floor(this.readPos);
      const end = Math.min(Math.max(start + 1, Math.floor(this.readPos + this.ratio)), this.pendingLen);
      let sum = 0;
      for (let i = start; i < end; i++) sum += this.pending[i];
      const sample = Math.max(-1, Math.min(1, sum / (end - start)));
      this.out[this.outLen++] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
      if (this.outLen === CHUNK_SAMPLES) {
        const chunk = this.out.slice(0);
        this.port.postMessage(chunk.buffer, [chunk.buffer]);
        this.outLen = 0;
      }
      this.readPos += this.ratio;
    }

    const consumed = Math.floor(this.readPos);
    if (consumed > 0) {
      this.pending.copyWithin(0, consumed, this.pendingLen);
      this.pendingLen -= consumed;
      this.readPos -= consumed;
    }
    return true;
  }
}

registerProcessor("capture-processor", CaptureProcessor);
