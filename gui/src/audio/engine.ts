import { BAND_LIMIT_HP_HZ, BAND_LIMIT_LP_HZ, monitorGain, type MonitorSettings, type SourceId } from "./gains";

export type LoadStatus = "ok" | "missing" | "error" | "none";

/** Player abstraction; the Listen screen talks only to this (tests use a fake). */
export interface AudioEngine {
  readonly supported: boolean;
  load(urls: Partial<Record<SourceId, string | null>>): Promise<Record<SourceId, LoadStatus>>;
  play(): Promise<void>;
  pause(): void;
  seek(seconds: number): void;
  isPlaying(): boolean;
  currentTime(): number;
  duration(): number;
  /** Linear gains per source (applied with a short ramp, click-free). */
  setSourceGains(gains: Record<SourceId, number>): void;
  setMonitor(settings: MonitorSettings): void;
  dispose(): void;
}

export type EngineFactory = () => AudioEngine;

const SOURCES: SourceId[] = ["before", "after", "delta"];
const RAMP_S = 0.008;

/**
 * Web Audio implementation. All sources are decoded to AudioBuffers and
 * started at the same instant; A/B switching only changes per-source GainNodes,
 * so the playback position is kept exactly.
 *
 * Graph: source[i] -> gain[i] -> sum -> (hp -> lp)? -> out -> destination.
 * Mono: `sum` is forced to one channel (speakers down-mix, (L+R)/2).
 */
export class WebAudioEngine implements AudioEngine {
  readonly supported: boolean;
  private ctx?: AudioContext;
  private buffers = new Map<SourceId, AudioBuffer>();
  private gains = new Map<SourceId, GainNode>();
  private nodes = new Map<SourceId, AudioBufferSourceNode>();
  private sum?: GainNode;
  private hp?: BiquadFilterNode;
  private lp?: BiquadFilterNode;
  private out?: GainNode;
  private playing = false;
  private startedAt = 0;
  private offset = 0;
  private wanted: Record<SourceId, number> = { before: 0, after: 0, delta: 0 };
  private monitor: MonitorSettings = { mono: false, bandLimit: false, lowLevel: false };

  constructor() {
    this.supported = typeof window !== "undefined" && typeof window.AudioContext === "function";
  }

  private ensure(): AudioContext {
    if (!this.ctx) {
      const ctx = new AudioContext();
      this.sum = ctx.createGain();
      this.hp = ctx.createBiquadFilter();
      this.hp.type = "highpass";
      this.hp.frequency.value = BAND_LIMIT_HP_HZ;
      this.lp = ctx.createBiquadFilter();
      this.lp.type = "lowpass";
      this.lp.frequency.value = BAND_LIMIT_LP_HZ;
      this.out = ctx.createGain();
      this.out.connect(ctx.destination);
      for (const id of SOURCES) {
        const g = ctx.createGain();
        g.gain.value = this.wanted[id];
        g.connect(this.sum);
        this.gains.set(id, g);
      }
      this.ctx = ctx;
      this.route();
    }
    return this.ctx;
  }

  private route() {
    const { sum, hp, lp, out, ctx } = this;
    if (!sum || !hp || !lp || !out || !ctx) return;
    sum.disconnect();
    hp.disconnect();
    lp.disconnect();
    sum.channelCount = this.monitor.mono ? 1 : 2;
    sum.channelCountMode = this.monitor.mono ? "explicit" : "max";
    sum.channelInterpretation = "speakers";
    if (this.monitor.bandLimit) {
      sum.connect(hp);
      hp.connect(lp);
      lp.connect(out);
    } else {
      sum.connect(out);
    }
    out.gain.setTargetAtTime(monitorGain(this.monitor), ctx.currentTime, RAMP_S);
  }

  async load(urls: Partial<Record<SourceId, string | null>>): Promise<Record<SourceId, LoadStatus>> {
    const status: Record<SourceId, LoadStatus> = { before: "none", after: "none", delta: "none" };
    if (!this.supported) return status;
    this.pause();
    this.offset = 0;
    this.buffers.clear();
    const ctx = this.ensure();
    await Promise.all(
      SOURCES.map(async (id) => {
        const url = urls[id];
        if (!url) return;
        try {
          const res = await fetch(url, { credentials: "same-origin" });
          if (!res.ok) {
            status[id] = "missing";
            return;
          }
          const buf = await ctx.decodeAudioData(await res.arrayBuffer());
          this.buffers.set(id, buf);
          status[id] = "ok";
        } catch {
          status[id] = "error";
        }
      }),
    );
    return status;
  }

  async play(): Promise<void> {
    if (!this.supported || this.playing || this.buffers.size === 0) return;
    const ctx = this.ensure();
    if (ctx.state === "suspended") await ctx.resume();
    if (this.offset >= this.duration()) this.offset = 0;
    const when = ctx.currentTime + 0.03;
    for (const [id, buf] of this.buffers) {
      const node = ctx.createBufferSource();
      node.buffer = buf;
      node.connect(this.gains.get(id)!);
      node.start(when, Math.min(this.offset, buf.duration));
      this.nodes.set(id, node);
    }
    this.startedAt = when - this.offset;
    this.playing = true;
  }

  pause(): void {
    if (!this.playing || !this.ctx) return;
    this.offset = this.currentTime();
    for (const n of this.nodes.values()) {
      try {
        n.stop();
      } catch {
        // already stopped
      }
      n.disconnect();
    }
    this.nodes.clear();
    this.playing = false;
  }

  seek(seconds: number): void {
    const wasPlaying = this.playing;
    this.pause();
    this.offset = Math.max(0, Math.min(seconds, this.duration()));
    if (wasPlaying) void this.play();
  }

  isPlaying(): boolean {
    if (this.playing && this.currentTime() >= this.duration()) {
      this.pause();
      this.offset = this.duration();
    }
    return this.playing;
  }

  currentTime(): number {
    if (!this.playing || !this.ctx) return this.offset;
    return Math.max(0, Math.min(this.ctx.currentTime - this.startedAt, this.duration()));
  }

  duration(): number {
    let d = 0;
    for (const b of this.buffers.values()) d = Math.max(d, b.duration);
    return d;
  }

  setSourceGains(gains: Record<SourceId, number>): void {
    this.wanted = { ...gains };
    if (!this.ctx) return;
    for (const id of SOURCES) this.gains.get(id)?.gain.setTargetAtTime(gains[id], this.ctx.currentTime, RAMP_S);
  }

  setMonitor(settings: MonitorSettings): void {
    this.monitor = { ...settings };
    this.route();
  }

  dispose(): void {
    this.pause();
    void this.ctx?.close();
    this.ctx = undefined;
    this.gains.clear();
    this.buffers.clear();
  }
}

export const defaultEngineFactory: EngineFactory = () => new WebAudioEngine();
