"use client";

// Scrollable simulated OBD-II telemetry recording (issue #52). The backend generates a
// deterministic 5-minute, 1 Hz recording per vehicle; this panel scrolls and zooms through it.
// Simulated POC data only: never mileage, service history, diagnostic, or recommendation evidence.

import { KeyboardEvent, PointerEvent, useEffect, useMemo, useState } from "react";
import { formatClockTime, formatTimeOfDay, useTimeZone } from "./display-prefs";

type Sample = { timestamp: string; value: number };
type Stream = { key: string; label: string; unit: string; samples: Sample[] };
export type StoredTelemetry = { capturedAt?: string; notice?: string; streams: Stream[] };
type Recording = { notice: string; capturedAt: string; durationSeconds: number; sampleRateHz: number; streams: Stream[] };

const WINDOWS = [
  { seconds: 15, label: "15 s" },
  { seconds: 30, label: "30 s" },
  { seconds: 60, label: "1 min" },
  { seconds: 300, label: "5 min" },
];

const fmt = (value: number) => (Number.isInteger(value) ? value.toLocaleString() : value.toLocaleString(undefined, { maximumFractionDigits: 1 }));

export function TelemetryPanel({ serial, stored }: { serial: string; stored?: StoredTelemetry }) {
  const { timeZone } = useTimeZone();
  const [recording, setRecording] = useState<Recording | null>(null);
  const [failed, setFailed] = useState(false);
  const [windowSeconds, setWindowSeconds] = useState(30);
  const [start, setStart] = useState(0);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    setRecording(null);
    setFailed(false);
    setStart(0);
    setHover(null);
    fetch(`/api/copilot/vehicles/${encodeURIComponent(serial)}/telemetry`, { headers: { Accept: "application/json" } })
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error(String(response.status)))))
      .then((data: Recording) => {
        if (!cancelled && Array.isArray(data.streams)) setRecording(data);
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [serial]);

  const total = recording?.streams[0]?.samples.length ?? 0;
  const size = Math.min(windowSeconds, total || windowSeconds);
  const maxStart = Math.max(0, total - size);
  const from = Math.min(start, maxStart);
  const to = from + size; // exclusive

  // Fixed y-scale per stream across the whole recording so lines don't jump while scrolling.
  const scales = useMemo(() => {
    const result: Record<string, { min: number; max: number }> = {};
    for (const stream of recording?.streams ?? []) {
      const values = stream.samples.map((s) => s.value);
      result[stream.key] = { min: Math.min(...values), max: Math.max(...values) };
    }
    return result;
  }, [recording]);

  function scroll(by: number) {
    setStart((current) => Math.max(0, Math.min(maxStart, Math.min(current, maxStart) + by)));
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.target instanceof HTMLInputElement) return; // the slider handles its own keys
    if (event.key === "ArrowLeft") { event.preventDefault(); scroll(-5); }
    if (event.key === "ArrowRight") { event.preventDefault(); scroll(5); }
    if (event.key === "Home") { event.preventDefault(); setStart(0); }
    if (event.key === "End") { event.preventDefault(); setStart(maxStart); }
  }

  function onPointer(event: PointerEvent<SVGSVGElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width));
    setHover(from + Math.round(ratio * (size - 1)));
  }

  const header = <div className="obd-panel-header"><div><h3 id="obd-title">OBD-II telemetry</h3><p>Simulated 5-minute recording for the POC · 1 sample per second</p></div><span className="obd-simulated-badge">SIMULATED</span></div>;
  const safety = "These values are not live vehicle readings and are never used for mileage, service history, diagnosis, or recommendations.";

  if (!recording) {
    const streams = stored?.streams ?? [];
    return (
      <section className="obd-card" aria-labelledby="obd-title">
        {header}
        <p className="obd-notice">{failed ? "The simulated recording could not load; showing the stored sample points instead." : "Loading the simulated recording…"} {safety}</p>
        {failed && streams.length > 0 && <div className="obd-stream-grid">{streams.map((stream) => {
          const latest = stream.samples[stream.samples.length - 1];
          return <article className="obd-stream" key={stream.key}><div className="obd-stream-title"><h4>{stream.label}</h4><strong>{latest ? fmt(latest.value) : "—"} <small>{stream.unit}</small></strong></div><p>{stream.samples.length} stored samples{latest ? ` · Latest ${formatTimeOfDay(latest.timestamp, timeZone)}` : ""}</p></article>;
        })}</div>}
      </section>
    );
  }

  const first = recording.streams[0].samples;
  const cursor = hover !== null && hover >= from && hover < to ? hover : null;

  return (
    <section className="obd-card" aria-labelledby="obd-title">
      {header}
      <p className="obd-notice">{recording.notice} {safety}</p>
      <div className="obd-controls" role="group" aria-label="Telemetry time window" tabIndex={0} onKeyDown={onKeyDown}>
        <div className="obd-zoom" role="radiogroup" aria-label="Window size">
          {WINDOWS.map((option) => (
            <button key={option.seconds} type="button" role="radio" aria-checked={windowSeconds === option.seconds} className={`copy-button ${windowSeconds === option.seconds ? "active" : ""}`}
              onClick={() => { setWindowSeconds(option.seconds); setStart((s) => Math.max(0, Math.min(s, total - Math.min(option.seconds, total)))); }}>{option.label}</button>
          ))}
        </div>
        <div className="obd-scroll">
          <button className="copy-button" type="button" onClick={() => scroll(-Math.max(1, Math.floor(size / 2)))} disabled={from === 0} aria-label="Earlier">◀</button>
          <input type="range" min={0} max={maxStart} step={1} value={from} onChange={(e) => setStart(Number(e.target.value))} disabled={maxStart === 0}
            aria-label="Scroll through the recording" aria-valuetext={`${formatClockTime(first[from].timestamp, timeZone)} to ${formatClockTime(first[to - 1].timestamp, timeZone)}`} />
          <button className="copy-button" type="button" onClick={() => scroll(Math.max(1, Math.floor(size / 2)))} disabled={from >= maxStart} aria-label="Later">▶</button>
        </div>
        <p className="obd-window-label" aria-live="polite">{formatClockTime(first[from].timestamp, timeZone)} – {formatClockTime(first[to - 1].timestamp, timeZone)} · {size} s of {total} s{cursor !== null ? ` · Cursor ${formatClockTime(first[cursor].timestamp, timeZone)}` : ""}</p>
      </div>
      <div className="obd-stream-grid">
        {recording.streams.map((stream) => {
          const windowSamples = stream.samples.slice(from, to);
          const values = windowSamples.map((s) => s.value);
          const { min, max } = scales[stream.key];
          const range = Math.max(1, max - min);
          const points = windowSamples.map((s, i) => `${size === 1 ? 0 : (i / (size - 1)) * 100},${34 - ((s.value - min) / range) * 28}`).join(" ");
          const shown = cursor !== null ? stream.samples[cursor] : windowSamples[windowSamples.length - 1];
          const cursorX = cursor !== null && size > 1 ? ((cursor - from) / (size - 1)) * 100 : null;
          const avg = values.reduce((a, b) => a + b, 0) / values.length;
          return (
            <article className="obd-stream" key={stream.key}>
              <div className="obd-stream-title"><h4>{stream.label}</h4><strong>{fmt(shown.value)} <small>{stream.unit}</small></strong></div>
              <svg className="obd-chart" viewBox="0 0 100 38" preserveAspectRatio="none" role="img" aria-label={`Simulated ${stream.label}: min ${fmt(Math.min(...values))}, max ${fmt(Math.max(...values))} ${stream.unit} in this window`}
                onPointerMove={onPointer} onPointerLeave={() => setHover(null)}>
                <polyline points={points} />
                {cursorX !== null && <line x1={cursorX} x2={cursorX} y1={0} y2={38} className="obd-cursor" />}
              </svg>
              <p>{cursor !== null ? `At ${formatClockTime(shown.timestamp, timeZone)}` : `Window min ${fmt(Math.min(...values))} · max ${fmt(Math.max(...values))} · avg ${fmt(Math.round(avg * 10) / 10)}`}</p>
            </article>
          );
        })}
      </div>
      <div className="obd-source-note">Source: synthetic recording generator · No adapter connected · Use ◀ ▶, the slider, or arrow keys to scroll; hover a chart to read values.</div>
    </section>
  );
}
