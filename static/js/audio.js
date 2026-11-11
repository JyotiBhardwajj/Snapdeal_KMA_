/**
 * AudioEngine: microphone capture (16 kHz PCM16 out) and model audio playback (24 kHz PCM16 in).
 * Two AudioContexts keep each side at its natural sample rate; worklets do the heavy lifting
 * off the main thread so the UI stays smooth.
 */
export class AudioEngine {
  constructor({ onMicChunk, onPlaybackChange } = {}) {
    this.onMicChunk = onMicChunk;
    this.onPlaybackChange = onPlaybackChange;
    this.playing = false;
    this._levelBuf = new Float32Array(512);
  }

  async start() {
    // Create the output context synchronously inside the click handler (autoplay policy).
    this.outCtx = new AudioContext({ sampleRate: 24000, latencyHint: "interactive" });
    const outReady = this.outCtx.audioWorklet.addModule("/static/js/worklets/playback.js");

    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });

    await outReady;
    this.player = new AudioWorkletNode(this.outCtx, "playback-processor", { outputChannelCount: [1] });
    this.outAnalyser = this.outCtx.createAnalyser();
    this.outAnalyser.fftSize = 512;
    this.player.connect(this.outAnalyser);
    this.outAnalyser.connect(this.outCtx.destination);
    this.player.port.onmessage = (event) => {
      this.playing = event.data.type === "started";
      this.onPlaybackChange?.(this.playing);
    };

    this.micCtx = new AudioContext({ latencyHint: "interactive" });
    await this.micCtx.audioWorklet.addModule("/static/js/worklets/capture.js");
    this.source = this.micCtx.createMediaStreamSource(this.stream);
    this.capture = new AudioWorkletNode(this.micCtx, "capture-processor");
    this.micAnalyser = this.micCtx.createAnalyser();
    this.micAnalyser.fftSize = 512;
    this.source.connect(this.micAnalyser);
    this.source.connect(this.capture);
    // Keep the worklet pulled by the graph without making the mic audible.
    const sink = this.micCtx.createGain();
    sink.gain.value = 0;
    this.capture.connect(sink).connect(this.micCtx.destination);
    this.capture.port.onmessage = (event) => this.onMicChunk?.(event.data);

    await Promise.all([this.outCtx.resume(), this.micCtx.resume()]);
  }

  /** Queue a chunk of 24 kHz little-endian PCM16 from the model. */
  play(arrayBuffer) {
    if (!this.player) return;
    const usable = arrayBuffer.byteLength - (arrayBuffer.byteLength % 2);
    const pcm = new Int16Array(arrayBuffer, 0, usable / 2);
    const samples = new Float32Array(pcm.length);
    for (let i = 0; i < pcm.length; i++) samples[i] = pcm[i] / 32768;
    this.player.port.postMessage({ type: "push", samples }, [samples.buffer]);
  }

  /** Play out whatever is buffered (end of a model turn). */
  flush() {
    this.player?.port.postMessage({ type: "flush" });
  }

  /** Drop queued audio immediately (the seller interrupted). */
  clear() {
    this.player?.port.postMessage({ type: "clear" });
  }

  setMicEnabled(enabled) {
    this.stream?.getAudioTracks().forEach((track) => (track.enabled = enabled));
  }

  _rms(analyser) {
    if (!analyser) return 0;
    analyser.getFloatTimeDomainData(this._levelBuf);
    let sum = 0;
    for (let i = 0; i < this._levelBuf.length; i++) sum += this._levelBuf[i] * this._levelBuf[i];
    return Math.sqrt(sum / this._levelBuf.length);
  }

  get micLevel() {
    return this._rms(this.micAnalyser);
  }

  get outLevel() {
    return this._rms(this.outAnalyser);
  }

  async stop() {
    this.stream?.getTracks().forEach((track) => track.stop());
    this.capture?.port.close();
    this.player?.port.close();
    await Promise.allSettled([this.micCtx?.close(), this.outCtx?.close()]);
    this.player = null;
    this.playing = false;
  }
}
