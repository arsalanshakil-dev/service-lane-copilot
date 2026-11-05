"use client";

import { FormEvent, Fragment, useEffect, useRef, useState } from "react";
import ChatPanel from "./chat-panel";
import { useAiModel } from "./ai-model";

type Recommendation = {
  name: string;
  status: string;
  kind: string;
  text: string;
  evidence: string;
  rule: string;
  safety?: boolean;
};

type HistoryEvent = {
  date: string;
  name: string;
  detail: string;
  mileage: string;
};

type TelemetrySample = { timestamp: string; value: number };
type TelemetryStream = { key: string; label: string; unit: string; samples: TelemetrySample[] };
type ObdTelemetry = { mode: "simulated"; status: "simulated"; source: string; capturedAt: string; notice: string; streams: TelemetryStream[] };

type Vehicle = {
  serial: string;
  make: string;
  model: string;
  year: number;
  mileage: number | null;
  mileageDate: string;
  mileageSource?: "advisor_observed" | "customer_reported";
  completeness: string;
  history: HistoryEvent[];
  recs: Recommendation[];
  obdTelemetry?: ObdTelemetry;
  incomplete?: boolean;
  conflicting?: boolean;
};

type DraftKind = "explanation" | "quote" | "followup";
type RecordDraftKind = "register" | "history";

type AiSuggestionsResult = {
  suggestions: Recommendation[];
  dropped: number;
  limitation: string | null;
  model: string;
};


/** POST JSON to the local backend and return parsed JSON, or throw a readable error. */
type View = "lane" | "records" | "settings";

function viewFromHash(hash: string): View {
  return hash === "#records" ? "records" : hash === "#settings" ? "settings" : "lane";
}

type RecordSummary = {
  serial: string;
  make: string | null;
  model: string | null;
  year: number | null;
  mileage: number | null;
  completeness: string | null;
  incomplete: boolean;
  conflicting: boolean;
  open_recommendations: number;
  history_count: number;
};

type RecordsPage = { total: number; count: number; limit: number; offset: number; vehicles: RecordSummary[] };

type AiSummaryResult = {
  serial: string;
  model: string;
  needs_now: string[];
  summary: string;
  open_items: { name: string; status: string; safety: boolean }[];
  limitation: string | null;
};

type SummaryState = { status: "loading" | "done" | "error"; data?: AiSummaryResult; error?: string };

function VehicleSummaryPanel({ serial, state, onOpen, onRetry }: { serial: string; state?: SummaryState; onOpen: () => void; onRetry: () => void }) {
  return (
    <div className="summary-panel" aria-live="polite" aria-busy={state?.status === "loading"}>
      <div className="summary-head"><strong>AI summary · {serial}</strong><span className="ai-tag">Unverified</span></div>
      {(!state || state.status === "loading") && <p className="summary-muted">Summarizing this record with your local model… this can take about a minute.</p>}
      {state?.status === "error" && <><p className="ai-error" role="alert">{state.error}</p><button className="copy-button" type="button" onClick={onRetry}>Try again</button></>}
      {state?.status === "done" && state.data && (
        <>
          {state.data.limitation && <div className="warning-banner"><b>!</b><span>{state.data.limitation}</span></div>}
          <div className="summary-block"><h4>Needs now <small>from the stored record</small></h4><ul className="summary-points">{state.data.needs_now.map((line) => <li key={line}>{line}</li>)}</ul></div>
          <div className="summary-block"><h4>AI context <small>local model {state.data.model} · unverified</small></h4><ul className="summary-points">{state.data.summary.split("\n").map((line) => line.replace(/^\s*[-*•]\s*/, "").trim()).filter(Boolean).map((line, index) => <li key={index}>{line}</li>)}</ul></div>
          <p className="source-note">“Needs now” is copied exactly from the stored recommendations. The AI context is written from the stored record only; verify it before discussing with the customer. Nothing is saved.</p>
        </>
      )}
      <div className="summary-actions"><button className="primary-button" type="button" onClick={onOpen}>Open record →</button></div>
    </div>
  );
}

const RECORDS_PAGE_SIZE = 25;

function SettingsView() {
  const { models, model, setModel, refresh, loading, error } = useAiModel();
  const [saved, setSaved] = useState(false);

  function choose(name: string) {
    setModel(name);
    setSaved(true);
    window.setTimeout(() => setSaved(false), 2000);
  }

  return (
    <section className="settings-view" aria-labelledby="settings-title">
      <div className="page-heading"><div><p className="eyebrow">SETTINGS</p><h1 id="settings-title">Settings</h1><p className="page-subtitle">Choices here apply to the whole app in this browser.</p></div></div>
      <div className="panel settings-panel">
        <div className="panel-title-row"><div><h3>AI model</h3><div className="panel-subtitle">Used by Ask Copilot, AI drafts, AI suggestions, and record summaries</div></div><span className="draft-type">LOCAL OLLAMA</span></div>
        <div className="settings-field">
          <label htmlFor="settings-ai-model">Local model</label>
          <div className="settings-control">
            <select id="settings-ai-model" value={model} onChange={(event) => choose(event.target.value)} disabled={loading || models.length === 0}>
              {models.length === 0 ? <option value="">{loading ? "Loading models…" : "No local model available"}</option> : models.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
            <button className="copy-button" type="button" onClick={refresh} disabled={loading}>{loading ? "Checking…" : "Refresh list"}</button>
          </div>
          <p className="settings-status" aria-live="polite">{saved ? `Saved. All AI features now use ${model}.` : error ? "" : loading ? "Checking local Ollama…" : `Ollama is running · ${models.length} chat model${models.length === 1 ? "" : "s"} installed · Embedding-only models are hidden.`}</p>
          {error && <p className="ai-error" role="alert">{error}</p>}
        </div>
        <p className="disclaimer">Models run on this computer through Ollama at 127.0.0.1:11434; nothing is sent to a cloud service. Larger models are slower on CPU-only machines. The choice is saved in this browser.</p>
      </div>
    </section>
  );
}

function RecordsView({ onOpen }: { onOpen: (serial: string) => void }) {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<RecordsPage | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  // Per-vehicle AI summaries (issue #38), cached for this browser session.
  const { model, loading: modelLoading } = useAiModel();
  const [openSummary, setOpenSummary] = useState<string | null>(null);
  const [summaries, setSummaries] = useState<Record<string, SummaryState>>({});

  async function summarize(recordSerial: string, force = false) {
    setOpenSummary((current) => (current === recordSerial && !force ? null : recordSerial));
    if (!model || (!force && summaries[recordSerial]?.status === "done") || summaries[recordSerial]?.status === "loading") return;
    if (!force && openSummary === recordSerial) return;
    setSummaries((current) => ({ ...current, [recordSerial]: { status: "loading" } }));
    try {
      const data = await postJson<AiSummaryResult>(`/api/copilot/vehicles/${encodeURIComponent(recordSerial)}/ai-summary`, { model });
      setSummaries((current) => ({ ...current, [recordSerial]: { status: "done", data } }));
    } catch (err) {
      setSummaries((current) => ({ ...current, [recordSerial]: { status: "error", error: err instanceof Error ? err.message : "The AI summary failed." } }));
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const params = new URLSearchParams({ q: submitted, limit: String(RECORDS_PAGE_SIZE), offset: String(offset) });
        const response = await fetch(`/api/copilot/vehicles?${params}`, { headers: { Accept: "application/json" } });
        // The dev proxy answers in plain text when the backend is down; never surface a JSON parse error.
        const text = await response.text();
        let data: (RecordsPage & { detail?: string }) | null = null;
        try {
          data = JSON.parse(text) as RecordsPage & { detail?: string };
        } catch {
          data = null;
        }
        if (!response.ok || !data) {
          throw new Error(data?.detail ?? `Could not load vehicle records (HTTP ${response.status}). Check that the backend is running, then try again.`);
        }
        if (!cancelled) setPage(data);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load vehicle records. Check that the backend is running.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [submitted, offset]);

  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setOffset(0);
    setSubmitted(query.trim());
  }

  const total = page?.total ?? 0;
  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + RECORDS_PAGE_SIZE, total);

  return (
    <section className="records-view" aria-labelledby="records-title">
      <div className="page-heading"><div><p className="eyebrow">VEHICLE RECORDS</p><h1 id="records-title">All vehicle records</h1><p className="page-subtitle">Browse or search every synthetic record. Select a vehicle to open it in the Service lane.</p></div></div>
      <div className="lookup-card">
        <form className="lookup-form" onSubmit={search} role="search">
          <label className="sr-only" htmlFor="records-search">Search by serial, make, model, or year</label>
          <div className="input-wrap"><span className="input-icon">⌕</span><input id="records-search" value={query} onChange={(event) => setQuery(event.target.value)} autoComplete="off" placeholder="Search serial, make, model, or year (e.g. Northstar, 2021)" /><button type="button" className={`clear-input ${query ? "visible" : ""}`} onClick={() => { setQuery(""); setOffset(0); setSubmitted(""); }} aria-label="Clear search">×</button></div>
          <button className="primary-button" type="submit">Search <span>→</span></button>
        </form>
        <p className="records-summary" aria-live="polite">{loading ? "Loading records…" : error ? "" : total === 0 ? (submitted ? `No records match “${submitted}”.` : "No records found.") : `Showing ${first.toLocaleString()}–${last.toLocaleString()} of ${total.toLocaleString()} records${submitted ? ` matching “${submitted}”` : ""}`}</p>
        {error && <p className="ai-error" role="alert">{error}</p>}
        <p className="records-ai-row">AI summaries use <strong>{model || (modelLoading ? "loading…" : "no model")}</strong> and the stored record only (about a minute each on CPU). <a href="#settings">Change model in Settings</a></p>
      </div>
      {page && page.vehicles.length > 0 && (
        <div className="records-table-wrap">
          <table className="records-table">
            <thead><tr><th scope="col">Serial</th><th scope="col">Vehicle</th><th scope="col">Mileage</th><th scope="col">Status</th><th scope="col">Open items</th><th scope="col">History</th><th scope="col">AI summary</th></tr></thead>
            <tbody>
              {page.vehicles.map((record) => {
                const summary = summaries[record.serial];
                const isOpen = openSummary === record.serial;
                return (
                  <Fragment key={record.serial}>
                    <tr className={isOpen ? "summary-open" : ""}>
                      <td><button type="button" className="record-link" onClick={() => onOpen(record.serial)}>{record.serial}</button></td>
                      <td>{[record.year, record.make, record.model].filter(Boolean).join(" ")}</td>
                      <td>{formatMiles(record.mileage)}</td>
                      <td><span className={`record-pill ${record.incomplete || record.conflicting ? "incomplete" : ""}`}>{record.completeness ?? "Unknown"}</span></td>
                      <td>{record.open_recommendations}</td>
                      <td>{record.history_count}</td>
                      <td><button type="button" className="copy-button ai-button" aria-expanded={isOpen} aria-controls={`summary-${record.serial}`} onClick={() => void summarize(record.serial)} disabled={!model}>{summary?.status === "loading" ? "Summarizing…" : isOpen ? "Hide summary" : "✦ AI summary"}</button></td>
                    </tr>
                    {isOpen && (
                      <tr className="summary-row" id={`summary-${record.serial}`}>
                        <td colSpan={7}>
                          <VehicleSummaryPanel serial={record.serial} state={summary} onOpen={() => onOpen(record.serial)} onRetry={() => void summarize(record.serial, true)} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {total > RECORDS_PAGE_SIZE && (
        <nav className="records-pager" aria-label="Records pages">
          <button className="copy-button" type="button" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - RECORDS_PAGE_SIZE))}>← Previous</button>
          <span>Page {Math.floor(offset / RECORDS_PAGE_SIZE) + 1} of {Math.ceil(total / RECORDS_PAGE_SIZE)}</span>
          <button className="copy-button" type="button" disabled={last >= total || loading} onClick={() => setOffset(offset + RECORDS_PAGE_SIZE)}>Next →</button>
        </nav>
      )}
    </section>
  );
}

type ServiceFormState = {
  recommendationName: string | null;
  serviceName: string;
  serviceDate: string;
  mileage: string;
  detail: string;
};

/** Today's date as YYYY-MM-DD in the advisor's local time zone. */
function todayIso(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
}

async function postJson<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  const text = await response.text();
  let data: { detail?: unknown } | null = null;
  try {
    data = JSON.parse(text) as { detail?: unknown };
  } catch {
    data = null;
  }
  if (!response.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : "";
    throw new Error(detail || `The local AI request failed (HTTP ${response.status}). Check that the backend and Ollama are running.`);
  }
  if (data === null) throw new Error("The local AI service returned an unreadable response.");
  return data as T;
}

const sampleSerials = [
  "NS-2048", "NS-7316", "NS-5192", "NS-8840", "NS-4402", "NS-1026", "NS-6621",
  "NS-3574", "NS-9031", "NS-2258", "DEMO-0011", "DEMO-0012", "DEMO-0013",
  "DEMO-0014", "DEMO-0015", "DEMO-0016",
];

function formatMiles(value: number | null): string {
  return value == null ? "Not recorded" : `${value.toLocaleString()} mi`;
}

function draftFor(vehicle: Vehicle, kind: DraftKind): string {
  const recommended = vehicle.recs
    .filter((item) => item.status === "Due" || item.status === "Coming up")
    .map((item) => item.name)
    .join(", ");
  const mileage = vehicle.mileage == null ? "not available" : `${vehicle.mileage.toLocaleString()} mi`;

  if (kind === "explanation") {
    return `Hello, based on the service history we have for your ${vehicle.year} ${vehicle.make} ${vehicle.model} (${vehicle.serial}) and the recorded mileage of ${mileage}, ${recommended ? `the following items may be due or coming up: ${recommended}.` : "we need an up-to-date mileage reading and complete service history before confirming what may be due."} These are suggestions from our demo schedule and should be checked by your service advisor.`;
  }
  if (kind === "quote") {
    return `Draft quote for advisor review\nVehicle: ${vehicle.year} ${vehicle.make} ${vehicle.model} · ${vehicle.serial}\nRecorded mileage: ${mileage}\nSuggested line items: ${recommended || "Not determined — verify current mileage and history first."}\nPricing: Add dealership-approved parts and labor pricing before sharing.\nNote: Demo recommendation only; advisor verification required.`;
  }
  return `Hello, this is a follow-up draft regarding your ${vehicle.year} ${vehicle.make} ${vehicle.model}. ${recommended ? `We reviewed the available history and would like to discuss: ${recommended}.` : "We are confirming the service history and mileage before making a recommendation."} Please contact our service team if you have questions.`;
}

function recordRequestDraft(vehicle: Vehicle, kind: RecordDraftKind): string {
  if (kind === "register") {
    return `Draft vehicle record update for advisor review\nSerial number: ${vehicle.serial}\nVehicle: ${vehicle.year} ${vehicle.make} ${vehicle.model}\nDetails to confirm: current odometer reading, date recorded, customer-provided service records\nIf readings conflict, retain both values and record the source; do not overwrite without verification.\nDo not submit until details are confirmed.`;
  }
  return `Draft request for another dealership to provide service history\nVehicle serial number: ${vehicle.serial}\nVehicle: ${vehicle.year} ${vehicle.make} ${vehicle.model}\nCustomer name and authorization: add after verification\nRequest: available service dates, service items performed, recorded mileage, and supporting maintenance documentation.\nAdvisor review: confirm recipient, customer authorization, and dealership process before sending.`;
}

function missingRecordDraft(serial: string, kind: RecordDraftKind): string {
  if (kind === "register") {
    return `Draft vehicle intake request for advisor review\nSerial number entered: ${serial}\nVehicle details to confirm: make, model, year, current odometer reading\nCustomer details and authorization: collect according to dealership procedure\nService history: attach records supplied by the customer or another dealership\nDo not submit until all details are confirmed.`;
  }
  return `Draft request for another dealership to provide service history\nVehicle serial number: ${serial}\nCustomer name and authorization: add after verification\nRequest: please provide available service dates, service items performed, recorded mileage, and any available maintenance documentation.\nAdvisor review: confirm recipient, customer authorization, and dealership process before sending.`;
}

async function copyText(value: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    return false;
  }
}

function formatTelemetryTime(timestamp: string): string {
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) return "Time unavailable";
  return `${parsed.toLocaleTimeString("en-PK", { timeZone: "Asia/Karachi", hour: "2-digit", minute: "2-digit" })} PKT`;
}

function TelemetryPanel({ telemetry }: { telemetry?: ObdTelemetry }) {
  const streams = telemetry?.streams ?? [];
  return (
    <section className="obd-card" aria-labelledby="obd-title">
      <div className="obd-panel-header"><div><h3 id="obd-title">OBD-II telemetry</h3><p>Simulated sample streams for the POC</p></div><span className="obd-simulated-badge">SIMULATED</span></div>
      <p className="obd-notice">{telemetry?.notice ?? "No simulated telemetry samples available."} These values are not live vehicle readings and are not used for mileage or service recommendations.</p>
      {streams.length === 0 ? <div className="obd-empty">No simulated telemetry samples available.</div> : <div className="obd-stream-grid">{streams.map((stream) => {
        const samples = stream.samples.filter((sample) => Number.isFinite(sample.value));
        if (samples.length === 0) return <article className="obd-stream" key={stream.key}><h4>{stream.label}</h4><p>No simulated samples available.</p></article>;
        const values = samples.map((sample) => sample.value);
        const min = Math.min(...values);
        const range = Math.max(1, Math.max(...values) - min);
        const points = samples.map((sample, index) => {
          const x = samples.length === 1 ? 0 : (index / (samples.length - 1)) * 100;
          const y = 32 - ((sample.value - min) / range) * 24;
          return `${x},${y}`;
        }).join(" ");
        const latest = samples[samples.length - 1];
        return <article className="obd-stream" key={stream.key}>
          <div className="obd-stream-title"><h4>{stream.label}</h4><strong>{latest.value.toLocaleString()} <small>{stream.unit}</small></strong></div>
          <svg className="obd-chart" viewBox="0 0 100 36" preserveAspectRatio="none" role="img" aria-label={`Simulated trend for ${stream.label}`}><polyline points={points} /></svg>
          <p>{samples.length} simulated samples · Latest {formatTelemetryTime(latest.timestamp)}</p>
        </article>;
      })}</div>}
      <div className="obd-source-note">Source: synthetic demo generator · No adapter connected</div>
    </section>
  );
}

export default function Home() {
  // "lane" = vehicle lookup and service work; "records" = list of all records. Driven by the URL hash
  // (#lane / #records) so the sidebar links and browser back/forward switch views.
  const [view, setView] = useState<View>("lane");
  useEffect(() => {
    const sync = () => setView(viewFromHash(window.location.hash));
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  function openRecord(recordSerial: string) {
    if (window.location.hash !== "#lane") window.location.hash = "#lane";
    setView("lane");
    window.scrollTo({ top: 0 });
    void lookup(recordSerial);
  }

  const [serial, setSerial] = useState("");
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [missingSerial, setMissingSerial] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeDraft, setActiveDraft] = useState<DraftKind>("explanation");
  const [draftText, setDraftText] = useState("");
  const [recordDraft, setRecordDraft] = useState("");
  const [toast, setToast] = useState("");
  const [manualMileage, setManualMileage] = useState("");
  const [manualMileageDate, setManualMileageDate] = useState("");
  const [manualMileageSource, setManualMileageSource] = useState<"advisor_observed" | "customer_reported">("advisor_observed");
  const [savingMileage, setSavingMileage] = useState(false);
  const [manualMileageOpen, setManualMileageOpen] = useState(false);
  const [serviceForm, setServiceForm] = useState<ServiceFormState | null>(null);
  const [savingService, setSavingService] = useState(false);
  // One model for every AI feature, chosen in Settings (issue #40).
  const { model: aiModel, error: aiModelsError, loading: aiModelLoading } = useAiModel();
  const [aiDraftModel, setAiDraftModel] = useState<string | null>(null);
  const [aiDraftBusy, setAiDraftBusy] = useState(false);
  const [aiDraftError, setAiDraftError] = useState("");
  const [aiSuggestions, setAiSuggestions] = useState<AiSuggestionsResult | null>(null);
  const [aiSuggestBusy, setAiSuggestBusy] = useState(false);
  const [aiSuggestError, setAiSuggestError] = useState("");
  // Ignore slow local-AI responses that arrive after the advisor has moved to another vehicle.
  const currentSerial = useRef("");


  function openServiceForm(recommendationName: string | null) {
    if (!vehicle) return;
    setServiceForm({
      recommendationName,
      serviceName: recommendationName ?? "",
      serviceDate: todayIso(),
      mileage: vehicle.mileage == null ? "" : String(vehicle.mileage),
      detail: "",
    });
  }

  async function saveService(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!vehicle || !serviceForm || savingService) return;
    setSavingService(true);
    try {
      const updated = await postJson<Vehicle>(`/api/copilot/vehicles/${encodeURIComponent(vehicle.serial)}/services`, {
        serviceName: serviceForm.serviceName,
        serviceDate: serviceForm.serviceDate,
        mileage: serviceForm.mileage === "" ? null : Number(serviceForm.mileage),
        detail: serviceForm.detail,
        recommendationName: serviceForm.recommendationName,
      });
      setVehicle(updated);
      setDraftText(draftFor(updated, activeDraft));
      resetAiOutput();
      setServiceForm(null);
      notify(`${serviceForm.serviceName} recorded and saved to the vehicle record`);
    } catch (error) {
      notify(error instanceof Error ? error.message : "Could not save the service.");
    } finally {
      setSavingService(false);
    }
  }

  function resetAiOutput() {
    setAiDraftModel(null);
    setAiDraftError("");
    setAiSuggestions(null);
    setAiSuggestError("");
  }

  async function generateAiDraft() {
    if (!vehicle || !aiModel || aiDraftBusy) return;
    const serialAtRequest = vehicle.serial;
    const kind = activeDraft;
    setAiDraftBusy(true);
    setAiDraftError("");
    try {
      const data = await postJson<{ draft_text: string; model: string }>(
        `/api/copilot/vehicles/${encodeURIComponent(serialAtRequest)}/ai-draft`,
        { model: aiModel, draftType: kind },
      );
      if (currentSerial.current !== serialAtRequest) return;
      setActiveDraft(kind);
      setDraftText(data.draft_text);
      setAiDraftModel(data.model);
    } catch (error) {
      if (currentSerial.current === serialAtRequest) {
        setAiDraftError(error instanceof Error ? error.message : "The local AI draft failed.");
      }
    } finally {
      setAiDraftBusy(false);
    }
  }

  async function suggestWithAi() {
    if (!vehicle || !aiModel || aiSuggestBusy) return;
    const serialAtRequest = vehicle.serial;
    setAiSuggestBusy(true);
    setAiSuggestError("");
    try {
      const data = await postJson<AiSuggestionsResult>(
        `/api/copilot/vehicles/${encodeURIComponent(serialAtRequest)}/ai-suggestions`,
        { model: aiModel },
      );
      if (currentSerial.current === serialAtRequest) setAiSuggestions(data);
    } catch (error) {
      if (currentSerial.current === serialAtRequest) {
        setAiSuggestError(error instanceof Error ? error.message : "The local AI suggestions failed.");
      }
    } finally {
      setAiSuggestBusy(false);
    }
  }

  function notify(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(""), 2200);
  }

  function toggleTheme() {
    const nextTheme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = nextTheme;
    try {
      window.localStorage.setItem("service-lane-theme", nextTheme);
    } catch {
      // The current page theme still changes if browser storage is unavailable.
    }
  }

  async function lookup(rawSerial: string) {
    const normalized = rawSerial.trim().toUpperCase();
    setSerial(normalized);
    if (!normalized) return;

    setLoading(true);
    currentSerial.current = normalized;
    resetAiOutput();
    setVehicle(null);
    setMissingSerial(null);
    setRecordDraft("");
    setManualMileage("");
    setManualMileageDate("");
    setManualMileageSource("advisor_observed");
    setManualMileageOpen(false);
    setServiceForm(null);
    try {
      const response = await fetch(`/api/copilot/vehicles/${encodeURIComponent(normalized)}`, {
        headers: { Accept: "application/json" },
      });
      if (response.status === 404) {
        setMissingSerial(normalized);
      } else if (!response.ok) {
        throw new Error("The vehicle service is unavailable.");
      } else {
        const data = (await response.json()) as Vehicle;
        setVehicle(data);
        setManualMileageOpen(data.mileage == null);
        setActiveDraft("explanation");
        setDraftText(draftFor(data, "explanation"));
      }
    } catch {
      notify("Could not reach the vehicle service. Start the backend and try again.");
    } finally {
      setLoading(false);
    }
  }

  function submitLookup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void lookup(serial);
  }

  async function saveManualMileage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!vehicle) return;
    setSavingMileage(true);
    try {
      const response = await fetch(`/api/copilot/vehicles/${encodeURIComponent(vehicle.serial)}/mileage`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          mileage: Number(manualMileage),
          mileageDate: manualMileageDate,
          mileageSource: manualMileageSource,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        notify(data.detail ?? "Could not save the mileage reading.");
        return;
      }
      const updatedVehicle = data as Vehicle;
      setVehicle(updatedVehicle);
      setDraftText(draftFor(updatedVehicle, activeDraft));
      // AI output was based on the old mileage; clear it so nothing stale is shown.
      resetAiOutput();
      setManualMileage("");
      setManualMileageDate("");
      setManualMileageOpen(false);
      notify(data.conflicting ? "Mileage saved; history conflict needs review" : "Mileage saved to the synthetic record");
    } catch {
      notify("Could not save the mileage. Check that the backend is running.");
    } finally {
      setSavingMileage(false);
    }
  }

  function chooseDraft(kind: DraftKind) {
    if (!vehicle) return;
    setActiveDraft(kind);
    setDraftText(draftFor(vehicle, kind));
    setAiDraftModel(null);
    setAiDraftError("");
  }

  async function copyDraft() {
    const copied = await copyText(draftText);
    if (copied) notify("Draft copied for your review");
    else notify("Copy is unavailable here; select and copy the draft text");
  }

  async function copyRecordDraft() {
    const copied = await copyText(recordDraft);
    if (copied) notify("Draft copied for your review");
    else notify("Copy is unavailable here; select and copy the draft text");
  }

  const incomplete = Boolean(vehicle && (vehicle.incomplete || vehicle.conflicting || vehicle.mileage == null));

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#main" aria-label="Lane home">
          <span className="brand-mark" aria-hidden="true">L</span><span>lane<span className="brand-dot">.</span></span>
        </a>
        <div className="dealer-switcher"><span className="dealer-icon">N</span><span className="dealer-copy"><strong>Northside Motors</strong><small>Service department</small></span><span className="chevron">⌄</span></div>
        <p className="nav-label">WORKSPACE</p>
        <nav aria-label="Main navigation"><a className={`nav-item ${view === "lane" ? "active" : ""}`} href="#lane" aria-current={view === "lane" ? "page" : undefined}><span className="nav-icon">⌕</span> Service lane</a><a className={`nav-item ${view === "records" ? "active" : ""}`} href="#records" aria-current={view === "records" ? "page" : undefined}><span className="nav-icon">▤</span> Vehicle records</a><a className={`nav-item ${view === "settings" ? "active" : ""}`} href="#settings" aria-current={view === "settings" ? "page" : undefined}><span className="nav-icon">⚙</span> Settings</a></nav>
        <div className="sidebar-bottom"><div className="advisor-profile"><span className="avatar">JD</span><span><strong>Jordan Davis</strong><small>Service advisor</small></span><span className="more">···</span></div></div>
      </aside>

      <main id="main" className="main-content">
        <header className="topbar"><div className="breadcrumbs">Workspace <span>/</span> <strong>{view === "records" ? "Vehicle records" : view === "settings" ? "Settings" : "Service lane"}</strong></div><nav className="mobile-view-switch" aria-label="Views"><a href="#lane" className={view === "lane" ? "active" : ""}>Lane</a><a href="#records" className={view === "records" ? "active" : ""}>Records</a><a href="#settings" className={view === "settings" ? "active" : ""} aria-label="Settings">⚙</a></nav><div className="topbar-right"><button className="theme-toggle" type="button" onClick={toggleTheme} aria-label="Toggle light and dark theme" title="Toggle light and dark theme"><span aria-hidden="true">◐</span><span className="theme-toggle-label">Theme</span></button><span className="live-dot" /> Synthetic data <span className="top-divider" /><a className="help-button" href="#demo-note" aria-label="About this demo" title="About this demo">?</a></div></header>
        {view === "settings" ? <SettingsView /> : view === "records" ? <RecordsView onOpen={openRecord} /> : (<>
        <section className="page-heading"><div><p className="eyebrow">SERVICE LANE</p><h1>Good morning, Jordan <span className="wave">✳</span></h1><p className="page-subtitle">Get ready for the next conversation. Start with a vehicle’s service history.</p></div><div className="date-chip"><span>◷</span> Demo appointments <strong>8</strong></div></section>

        <section className="lookup-card" aria-labelledby="lookup-title">
          <div className="lookup-intro"><div className="lookup-icon">⌕</div><div><h2 id="lookup-title">Look up a vehicle</h2><p>Enter the vehicle serial number or VIN to see its service history and recommendations.</p></div></div>
          <form className="lookup-form" onSubmit={submitLookup}><label className="sr-only" htmlFor="serial-input">Vehicle serial number or VIN</label><div className="input-wrap"><span className="input-icon">▤</span><input id="serial-input" value={serial} onChange={(event) => setSerial(event.target.value)} autoComplete="off" placeholder="Enter serial number or VIN (e.g. NS-2048)" /><button type="button" className={`clear-input ${serial ? "visible" : ""}`} onClick={() => setSerial("")} aria-label="Clear serial number">×</button></div><button className="primary-button" type="submit" disabled={loading}>{loading ? "Looking up…" : "Find vehicle"} <span>→</span></button></form>
          <div className="lookup-hint"><span className="hint-icon">✦</span> Try a sample: {sampleSerials.map((item, index) => <span className="sample-choice" key={item}><button className="sample-link" type="button" onClick={() => void lookup(item)}>{item}</button>{index < sampleSerials.length - 1 && <span className="sample-separator">·</span>}</span>)}</div>
        </section>

        {!vehicle && !missingSerial && <div className="welcome-state"><div className="welcome-art" aria-hidden="true"><div className="art-orbit orbit-one" /><div className="art-orbit orbit-two" /><div className="art-car">▰</div><div className="art-spark spark-one">✳</div><div className="art-spark spark-two">✦</div></div><div className="welcome-copy"><h2>Make every visit feel prepared.</h2><p>Look up a sample vehicle to review its service history, see what may be coming up, and prepare a draft for the customer.</p><div className="welcome-steps"><span><i>1</i> Find vehicle</span><span className="step-line" /><span><i>2</i> Review history</span><span className="step-line" /><span><i>3</i> Prepare a draft</span></div></div></div>}

        {vehicle && <div className="result-layout">
          <section className="vehicle-card">
            <div className="vehicle-top"><div className="vehicle-ident"><div className="car-badge">▰</div><div><h2>{vehicle.year} {vehicle.make} {vehicle.model}</h2><p>Serial number {vehicle.serial}</p></div></div><span className={`record-pill ${incomplete ? "incomplete" : ""}`}>{vehicle.completeness}</span></div>
            <div className="vehicle-meta"><div><div className="meta-label">CURRENT MILEAGE</div><div className="meta-value">{formatMiles(vehicle.mileage)}</div><div className="meta-sub">{vehicle.mileageDate}{vehicle.mileageSource ? ` · ${vehicle.mileageSource === "advisor_observed" ? "Advisor-observed" : "Customer-reported"}` : ""}</div>{vehicle.mileage != null && <button className="meta-action" type="button" aria-expanded={manualMileageOpen} onClick={() => setManualMileageOpen((open) => !open)}>{manualMileageOpen ? "Cancel update" : "Update mileage"}</button>}</div><div><div className="meta-label">HISTORY EVENTS</div><div className="meta-value">{vehicle.history.length} recorded</div><div className="meta-sub">Synthetic dealer record</div></div><div><div className="meta-label">RECORD STATUS</div><div className="meta-value">{incomplete ? "Needs attention" : "Ready to review"}</div><div className="meta-sub">Synthetic dataset</div></div></div>
            <TelemetryPanel telemetry={vehicle.obdTelemetry} />
            {(vehicle.mileage == null || manualMileageOpen) && <section className="manual-mileage" aria-labelledby="manual-mileage-title"><div><h3 id="manual-mileage-title">{vehicle.mileage == null ? "Enter current mileage" : "Replace current mileage"}</h3><p>{vehicle.mileage == null ? "No odometer reading is available. Record a manual reading for this synthetic vehicle." : "Enter an advisor-confirmed reading to replace the current synthetic mileage. The previous value is not retained."}</p></div><form className="manual-mileage-form" onSubmit={saveManualMileage}><label>Odometer miles<input type="number" min="0" step="1" inputMode="numeric" required value={manualMileage} onChange={(event) => setManualMileage(event.target.value)} placeholder="e.g. 48,120" /></label><label>Reading date<input type="date" required value={manualMileageDate} onChange={(event) => setManualMileageDate(event.target.value)} /></label><label>Reading source<select value={manualMileageSource} onChange={(event) => setManualMileageSource(event.target.value as "advisor_observed" | "customer_reported")}><option value="advisor_observed">Advisor-observed</option><option value="customer_reported">Customer-reported</option></select></label><button className="primary-button manual-mileage-submit" type="submit" disabled={savingMileage}>{savingMileage ? "Saving…" : "Save mileage"}</button></form><p className="manual-mileage-note">Saving replaces the current mileage field. Earlier mileage is not retained. Recommendations remain paused if service-history evidence is incomplete or conflicting.</p></section>}
            {incomplete && <><div className="warning-banner"><b>!</b><span>{vehicle.conflicting ? "Mileage conflict: a recorded service mileage is higher than the current odometer reading. Reconcile the records before using service timing." : vehicle.mileage != null && vehicle.completeness === "History incomplete" ? "Current mileage is recorded, but service history is incomplete or missing event mileage. Recommendations remain paused until the advisor can verify supporting history; do not infer a due service." : vehicle.mileage != null ? "The mileage record is old, so service timing cannot be confirmed. Ask the customer for the current odometer reading and verify the record." : "Mileage is missing and service history is incomplete. Do not infer a due service from this record. Get a current odometer reading and request the missing history."}</span></div><div className="path-grid record-paths"><article className="path-card"><h3>Update dealership service record</h3><p>Prepare an intake draft to confirm vehicle details, mileage, and missing service history.</p><button type="button" onClick={() => setRecordDraft(recordRequestDraft(vehicle, "register"))}>Prepare registration draft</button></article><article className="path-card"><h3>Request outside service history</h3><p>Prepare a request for advisor review. No lookup or message is sent.</p><button type="button" onClick={() => setRecordDraft(recordRequestDraft(vehicle, "history"))}>Prepare history request</button></article></div>{recordDraft && <DraftEditor label="Record request draft" value={recordDraft} onChange={setRecordDraft} onCopy={copyRecordDraft} />}</>}
            <div className="section-heading"><h3>{incomplete ? "Recommendations" : "Service recommendations"}</h3><span className="count-badge">{incomplete ? "Evidence needed" : `${vehicle.recs.length} items to review`}</span></div>
            {incomplete ? <div className="evidence">{vehicle.mileage == null ? "Recommendations are paused until a current mileage reading and relevant service history are verified." : "Manual mileage is saved, but service-history evidence is still incomplete. Recommendations remain paused until the advisor can verify it."}</div> : vehicle.recs.length ? vehicle.recs.map((rec, index) => <div key={`${rec.name}-${index}`}><RecommendationCard rec={rec} onComplete={rec.kind === "done" ? undefined : () => openServiceForm(rec.name)} />{serviceForm?.recommendationName === rec.name && <ServiceForm form={serviceForm} saving={savingService} onChange={setServiceForm} onSubmit={saveService} onCancel={() => setServiceForm(null)} />}</div>) : <div className="evidence">No items match the configured demo rules. This does not replace review against an approved maintenance schedule.</div>}
            <AiSuggestionsSection
              result={aiSuggestions}
              busy={aiSuggestBusy}
              error={aiSuggestError}
              model={aiModel}
              modelsError={aiModelsError}
              onSuggest={() => void suggestWithAi()}
            />
            <div className="history-list"><div className="section-heading"><h3>Service history</h3><span className="history-actions"><span className="count-badge">{vehicle.history.length} events</span><button className="copy-button" type="button" onClick={() => openServiceForm(null)} disabled={savingService}>+ Record service</button></span></div>{serviceForm && serviceForm.recommendationName === null && <ServiceForm form={serviceForm} saving={savingService} onChange={setServiceForm} onSubmit={saveService} onCancel={() => setServiceForm(null)} />}{vehicle.history.map((event, index) => <div className="history-row" key={`${event.name}-${index}`}><span className="history-date">{event.date}</span><span className="history-name">{event.name}<span className="history-detail">{event.detail}</span></span><span className="history-mileage">{event.mileage}</span></div>)}</div>
          </section>
          <aside className="side-column"><section className="panel"><div className="panel-title-row"><div><h3>Customer drafts</h3><div className="panel-subtitle">Editable · Nothing is sent</div></div><span className="draft-type">FOR REVIEW</span></div><div className="draft-tabs" role="tablist" aria-label="Customer draft type">{(["explanation", "quote", "followup"] as DraftKind[]).map((kind) => <button key={kind} className={`draft-tab ${activeDraft === kind ? "active" : ""}`} role="tab" aria-selected={activeDraft === kind} type="button" onClick={() => chooseDraft(kind)}>{kind === "followup" ? "Follow-up" : kind[0].toUpperCase() + kind.slice(1)}</button>)}</div><div className="ai-draft-row"><span className="ai-model-note">Model: <strong>{aiModel || (aiModelLoading ? "loading…" : "none")}</strong> · <a href="#settings">Settings</a></span><button className="copy-button ai-button" type="button" onClick={() => void generateAiDraft()} disabled={!aiModel || aiDraftBusy}>{aiDraftBusy ? "Writing… (can take a few minutes)" : "✦ Generate with local AI"}</button></div>{(aiDraftError || aiModelsError) && <p className="ai-error" role="alert">{aiDraftError || aiModelsError} The template draft is still available.</p>}<textarea className="draft-editor" aria-label="Editable customer draft" aria-busy={aiDraftBusy} value={draftText} onChange={(event) => setDraftText(event.target.value)} /><div className="draft-actions"><span className="draft-status">{aiDraftModel ? `Written by local AI (${aiDraftModel}) · review before sharing` : "Template draft · Review details before sharing"}</span><button className="copy-button" type="button" onClick={() => void copyDraft()}>Copy draft</button></div><p className="disclaimer">Draft text is based only on the synthetic record and demo rules. Check all details and pricing before use.</p></section><section className="panel"><div className="panel-title-row"><div><h3>Record details</h3><div className="panel-subtitle">From synthetic dealership history</div></div><span className="draft-type">DEMO</span></div><div className="evidence"><strong>Lookup key</strong><br />Synthetic vehicle serial: {vehicle.serial}</div><div className="evidence" style={{ marginTop: 8 }}><strong>Planned vehicle source</strong><br />OBD-II/CAN may provide a VIN; make, model, and year can be decoded from it. Odometer support varies by vehicle and adapter. This demo uses synthetic data; service history remains separate.</div><p className="disclaimer">No physical vehicle or dealership system is connected.</p></section></aside>
        </div>}

        {missingSerial && <section className="empty-result"><div className="empty-icon">⌕</div><h2>No demo record found for {missingSerial}</h2><p>This serial number is not in the synthetic dealership dataset. Check the number, register the vehicle in dealership service records, or request service history from another dealership. The requests below are drafts for the advisor to review.</p><div className="path-grid"><article className="path-card"><h3>Add to dealership service records</h3><p>Prepare a draft intake request. Confirm vehicle details and customer authorization through dealership procedures.</p><button type="button" onClick={() => setRecordDraft(missingRecordDraft(missingSerial, "register"))}>Prepare registration draft</button></article><article className="path-card"><h3>Request outside service history</h3><p>Prepare a request for the customer or advisor to use with another dealership. No lookup or message is sent.</p><button type="button" onClick={() => setRecordDraft(missingRecordDraft(missingSerial, "history"))}>Prepare history request</button></article></div>{recordDraft && <DraftEditor label="Record request draft" value={recordDraft} onChange={setRecordDraft} onCopy={copyRecordDraft} />}</section>}

        </>)}

        <footer id="demo-note" className="page-footer"><span>ⓘ</span> Demo only: synthetic vehicle records and example maintenance rules. Verify any safety-related item against an approved source.</footer>
      </main>
      <ChatPanel />
      {toast && <div className="toast show" role="status">{toast}</div>}
    </div>
  );
}

function AiSuggestionsSection({ result, busy, error, model, modelsError, onSuggest }: { result: AiSuggestionsResult | null; busy: boolean; error: string; model: string; modelsError: string; onSuggest: () => void }) {
  return (
    <section className="ai-suggestions" aria-labelledby="ai-suggestions-title" aria-busy={busy}>
      <div className="section-heading"><h3 id="ai-suggestions-title">AI suggestions <span className="ai-tag">Unverified</span></h3><button className="copy-button ai-button" type="button" onClick={onSuggest} disabled={!model || busy}>{busy ? "Thinking… (can take a few minutes)" : "✦ Suggest more with local AI"}</button></div>
      <p className="source-note">Extra items from your local model{model ? ` (${model})` : ""}, based on current mileage and service history. Intervals shown are the model's estimate, not a manufacturer schedule; verify before use. Items without history evidence, with prices, or done too recently are removed.</p>
      {!model && modelsError && <p className="ai-error" role="alert">{modelsError}</p>}
      {error && <p className="ai-error" role="alert">{error}</p>}
      {result?.limitation && <div className="evidence">{result.limitation}</div>}
      {result && !result.limitation && result.suggestions.length === 0 && <div className="evidence">The local model found no additional items supported by the recorded history.</div>}
      {result?.suggestions.map((rec, index) => <RecommendationCard key={`ai-${rec.name}-${index}`} rec={rec} />)}
      {result && result.dropped > 0 && <p className="source-note">{result.dropped} suggestion{result.dropped === 1 ? " was" : "s were"} removed for missing history evidence, prices, duplicating a stored recommendation, or being done too recently.</p>}
    </section>
  );
}

function RecommendationCard({ rec, onComplete }: { rec: Recommendation; onComplete?: () => void }) {
  const done = rec.kind === "done";
  const kind = done ? "done" : rec.kind === "safety" ? "safety" : rec.status === "Not yet due" ? "neutral" : rec.kind;
  return <article className={`recommendation ${done ? "completed" : ""}`}><div className="rec-top"><span className="rec-title">{done && <span aria-hidden="true">✓ </span>}{rec.name}</span><span className={`status ${kind}`}>{rec.status}</span></div><p className="rec-copy">{rec.text}</p><div className="evidence"><strong>{done ? "Completion record" : "Why it appears"}</strong><br />{rec.evidence}</div><p className="source-note">{rec.rule}</p>{rec.safety && !done && <div className="warning-banner"><b>!</b><span>Safety-related: verify against an approved source before discussing or recommending work.</span></div>}{onComplete && <div className="rec-actions"><button className="copy-button" type="button" onClick={onComplete}>✓ Mark as done</button></div>}</article>;
}

function ServiceForm({ form, saving, onChange, onSubmit, onCancel }: { form: ServiceFormState; saving: boolean; onChange: (form: ServiceFormState) => void; onSubmit: (event: FormEvent<HTMLFormElement>) => void; onCancel: () => void }) {
  const fixedName = form.recommendationName !== null;
  return (
    <form className="service-form" onSubmit={onSubmit} aria-label={fixedName ? `Record ${form.serviceName} as done` : "Record a completed service"}>
      <h4>{fixedName ? `Record “${form.serviceName}” as done` : "Record a completed service"}</h4>
      <div className="service-form-grid">
        {!fixedName && <label>Service<input required maxLength={80} value={form.serviceName} onChange={(event) => onChange({ ...form, serviceName: event.target.value })} placeholder="e.g. Wiper blades" /></label>}
        <label>Date done<input type="date" required max={todayIso()} value={form.serviceDate} onChange={(event) => onChange({ ...form, serviceDate: event.target.value })} /></label>
        <label>Odometer (mi)<input type="number" min="0" step="1" inputMode="numeric" value={form.mileage} onChange={(event) => onChange({ ...form, mileage: event.target.value })} placeholder="Leave blank if not read" /></label>
        <label className="service-form-note">Note (optional)<input maxLength={200} value={form.detail} onChange={(event) => onChange({ ...form, detail: event.target.value })} placeholder="e.g. Synthetic oil, OEM filter" /></label>
      </div>
      <p className="manual-mileage-note">Saved to the vehicle record. Adds a service-history entry{fixedName ? " and marks this recommendation Completed" : ""}. A higher odometer reading also updates current mileage. No next-due date is calculated.</p>
      <div className="service-form-actions"><button className="copy-button" type="button" onClick={onCancel} disabled={saving}>Cancel</button><button className="primary-button" type="submit" disabled={saving}>{saving ? "Saving…" : "Save service"}</button></div>
    </form>
  );
}

function DraftEditor({ label, value, onChange, onCopy }: { label: string; value: string; onChange: (value: string) => void; onCopy: () => void }) {
  return <div className="draft-generated"><label>{label}<textarea value={value} onChange={(event) => onChange(event.target.value)} /></label><div className="draft-actions"><span className="draft-status">Draft only · Not submitted</span><button className="copy-button" type="button" onClick={onCopy}>Copy draft</button></div></div>;
}
