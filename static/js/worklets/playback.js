/**
 * Playback worklet: a FIFO of Float32 chunks played back-to-back without gaps.
 * - {type: "push", samples} appends audio from the model (24 kHz).
 * - {type: "clear"} drops everything instantly (used for barge-in / interruption).
 * Posts {type: "started"} / {type: "drained"} so the UI knows when Disha is talking.
 */
const PREBUFFER_SAMPLES = 2400; // 100 ms at 24 kHz smooths network jitter at the start of a turn

class PlaybackProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.queue = [];
    this.queued = 0;
    this.current = null;
    this.offset = 0;
    this.playing = false;
    this.buffering = true;
    this.port.onmessage = (event) => {
      const msg = event.data;
      if (msg.type === "push") {
        this.queue.push(msg.samples);
        this.queued += msg.samples.length;
      } else if (msg.type === "clear") {
        this.queue = [];
        this.queued = 0;
        this.current = null;
        this.offset = 0;
        this.buffering = true;
        this.setPlaying(false);
      } else if (msg.type === "flush") {
        this.buffering = false; // play whatever is left even if below the pre-buffer
      }
    };
  }

  setPlaying(value) {
    if (value !== this.playing) {
      this.playing = value;
      this.port.postMessage({ type: value ? "started" : "drained" });
    }
  }

  process(_inputs, outputs) {
    const out = outputs[0][0];
    if (this.buffering && this.queued < PREBUFFER_SAMPLES && !this.current) {
      out.fill(0);
      return true;
    }
    this.buffering = false;

    let written = 0;
    while (written < out.length) {
      if (!this.current) {
        this.current = this.queue.shift() || null;
        this.offset = 0;
        if (!this.current) break;
      }
      const n = Math.min(out.length - written, this.current.length - this.offset);
      out.set(this.current.subarray(this.offset, this.offset + n), written);
      written += n;
      this.offset += n;
      this.queued -= n;
      if (this.offset >= this.current.length) this.current = null;
    }
    if (written < out.length) out.fill(0, written);

    if (written > 0) {
      this.setPlaying(true);
    } else {
      this.buffering = true;
      this.setPlaying(false);
    }
    return true;
  }
}

registerProcessor("playback-processor", PlaybackProcessor);
