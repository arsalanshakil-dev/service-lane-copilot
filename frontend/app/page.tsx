"use client";

import { FormEvent, useState } from "react";

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

type Vehicle = {
  serial: string;
  make: string;
  model: string;
  year: number;
  mileage: number | null;
  mileageDate: string;
  completeness: string;
  history: HistoryEvent[];
  recs: Recommendation[];
  incomplete?: boolean;
  conflicting?: boolean;
};

type DraftKind = "explanation" | "quote" | "followup";
type RecordDraftKind = "register" | "history";

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

export default function Home() {
  const [serial, setSerial] = useState("");
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [missingSerial, setMissingSerial] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeDraft, setActiveDraft] = useState<DraftKind>("explanation");
  const [draftText, setDraftText] = useState("");
  const [recordDraft, setRecordDraft] = useState("");
  const [toast, setToast] = useState("");

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
    setVehicle(null);
    setMissingSerial(null);
    setRecordDraft("");
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

  function chooseDraft(kind: DraftKind) {
    if (!vehicle) return;
    setActiveDraft(kind);
    setDraftText(draftFor(vehicle, kind));
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
        <nav aria-label="Main navigation"><a className="nav-item active" href="#main"><span className="nav-icon">⌕</span> Service lane</a><a className="nav-item muted" href="#demo-note"><span className="nav-icon">▤</span> Vehicle records <span className="soon">DEMO</span></a></nav>
        <div className="sidebar-bottom"><div className="demo-card"><span className="demo-spark">✳</span><strong>Demo workspace</strong><p>250 fictional vehicle records with example service histories and rules.</p><a href="#demo-note">About this demo <span>↗</span></a></div><div className="advisor-profile"><span className="avatar">JD</span><span><strong>Jordan Davis</strong><small>Service advisor</small></span><span className="more">···</span></div></div>
      </aside>

      <main id="main" className="main-content">
        <header className="topbar"><div className="breadcrumbs">Workspace <span>/</span> <strong>Service lane</strong></div><div className="topbar-right"><button className="theme-toggle" type="button" onClick={toggleTheme} aria-label="Toggle light and dark theme" title="Toggle light and dark theme"><span aria-hidden="true">◐</span><span className="theme-toggle-label">Theme</span></button><span className="live-dot" /> Synthetic data <span className="top-divider" /><button className="help-button" aria-label="Help">?</button></div></header>
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
            <div className="vehicle-meta"><div><div className="meta-label">CURRENT MILEAGE</div><div className="meta-value">{formatMiles(vehicle.mileage)}</div><div className="meta-sub">{vehicle.mileageDate}</div></div><div><div className="meta-label">HISTORY EVENTS</div><div className="meta-value">{vehicle.history.length} recorded</div><div className="meta-sub">Synthetic dealer record</div></div><div><div className="meta-label">RECORD STATUS</div><div className="meta-value">{incomplete ? "Needs attention" : "Ready to review"}</div><div className="meta-sub">Synthetic dataset</div></div></div>
            {incomplete && <><div className="warning-banner"><b>!</b><span>{vehicle.conflicting ? "Mileage conflict: a recorded service mileage is higher than the current odometer reading. Reconcile the records before using service timing." : vehicle.mileage != null ? "The mileage record is old, so service timing cannot be confirmed. Ask the customer for the current odometer reading and verify the record." : "Mileage is missing and service history is incomplete. Do not infer a due service from this record. Get a current odometer reading and request the missing history."}</span></div><div className="path-grid record-paths"><article className="path-card"><h3>Update dealership service record</h3><p>Prepare an intake draft to confirm vehicle details, mileage, and missing service history.</p><button type="button" onClick={() => setRecordDraft(recordRequestDraft(vehicle, "register"))}>Prepare registration draft</button></article><article className="path-card"><h3>Request outside service history</h3><p>Prepare a request for advisor review. No lookup or message is sent.</p><button type="button" onClick={() => setRecordDraft(recordRequestDraft(vehicle, "history"))}>Prepare history request</button></article></div>{recordDraft && <DraftEditor label="Record request draft" value={recordDraft} onChange={setRecordDraft} onCopy={copyRecordDraft} />}</>}
            <div className="section-heading"><h3>{incomplete ? "Recommendations" : "Service recommendations"}</h3><span className="count-badge">{incomplete ? "Evidence needed" : `${vehicle.recs.length} items to review`}</span></div>
            {incomplete ? <div className="evidence">Recommendations are paused until the advisor can verify current mileage and relevant service history.</div> : vehicle.recs.length ? vehicle.recs.map((rec, index) => <RecommendationCard key={`${rec.name}-${index}`} rec={rec} />) : <div className="evidence">No items match the configured demo rules. This does not replace review against an approved maintenance schedule.</div>}
            <div className="history-list"><div className="section-heading"><h3>Service history</h3><span className="count-badge">{vehicle.history.length} events</span></div>{vehicle.history.map((event, index) => <div className="history-row" key={`${event.name}-${index}`}><span className="history-date">{event.date}</span><span className="history-name">{event.name}<span className="history-detail">{event.detail}</span></span><span className="history-mileage">{event.mileage}</span></div>)}</div>
          </section>
          <aside className="side-column"><section className="panel"><div className="panel-title-row"><div><h3>Customer drafts</h3><div className="panel-subtitle">Editable · Nothing is sent</div></div><span className="draft-type">FOR REVIEW</span></div><div className="draft-tabs" role="tablist" aria-label="Customer draft type">{(["explanation", "quote", "followup"] as DraftKind[]).map((kind) => <button key={kind} className={`draft-tab ${activeDraft === kind ? "active" : ""}`} role="tab" aria-selected={activeDraft === kind} type="button" onClick={() => chooseDraft(kind)}>{kind === "followup" ? "Follow-up" : kind[0].toUpperCase() + kind.slice(1)}</button>)}</div><textarea className="draft-editor" aria-label="Editable customer draft" value={draftText} onChange={(event) => setDraftText(event.target.value)} /><div className="draft-actions"><span className="draft-status">Review details before sharing</span><button className="copy-button" type="button" onClick={() => void copyDraft()}>Copy draft</button></div><p className="disclaimer">Draft text is based only on the synthetic record and demo rules. Check all details and pricing before use.</p></section><section className="panel"><div className="panel-title-row"><div><h3>Record details</h3><div className="panel-subtitle">From synthetic dealership history</div></div><span className="draft-type">DEMO</span></div><div className="evidence"><strong>Lookup key</strong><br />Synthetic vehicle serial: {vehicle.serial}</div><div className="evidence" style={{ marginTop: 8 }}><strong>Planned vehicle source</strong><br />OBD-II/CAN may provide a VIN; make, model, and year can be decoded from it. Odometer support varies by vehicle and adapter. This demo uses synthetic data; service history remains separate.</div><p className="disclaimer">No physical vehicle or dealership system is connected.</p></section></aside>
        </div>}

        {missingSerial && <section className="empty-result"><div className="empty-icon">⌕</div><h2>No demo record found for {missingSerial}</h2><p>This serial number is not in the synthetic dealership dataset. Check the number, register the vehicle in dealership service records, or request service history from another dealership. The requests below are drafts for the advisor to review.</p><div className="path-grid"><article className="path-card"><h3>Add to dealership service records</h3><p>Prepare a draft intake request. Confirm vehicle details and customer authorization through dealership procedures.</p><button type="button" onClick={() => setRecordDraft(missingRecordDraft(missingSerial, "register"))}>Prepare registration draft</button></article><article className="path-card"><h3>Request outside service history</h3><p>Prepare a request for the customer or advisor to use with another dealership. No lookup or message is sent.</p><button type="button" onClick={() => setRecordDraft(missingRecordDraft(missingSerial, "history"))}>Prepare history request</button></article></div>{recordDraft && <DraftEditor label="Record request draft" value={recordDraft} onChange={setRecordDraft} onCopy={copyRecordDraft} />}</section>}

        <footer id="demo-note" className="page-footer"><span>ⓘ</span> Demo only: synthetic vehicle records and example maintenance rules. Verify any safety-related item against an approved source.</footer>
      </main>
      {toast && <div className="toast show" role="status">{toast}</div>}
    </div>
  );
}

function RecommendationCard({ rec }: { rec: Recommendation }) {
  const kind = rec.kind === "safety" ? "safety" : rec.status === "Not yet due" ? "neutral" : rec.kind;
  return <article className="recommendation"><div className="rec-top"><span className="rec-title">{rec.name}</span><span className={`status ${kind}`}>{rec.status}</span></div><p className="rec-copy">{rec.text}</p><div className="evidence"><strong>Why it appears</strong><br />{rec.evidence}</div><p className="source-note">{rec.rule}</p>{rec.safety && <div className="warning-banner"><b>!</b><span>Safety-related: verify against an approved source before discussing or recommending work.</span></div>}</article>;
}

function DraftEditor({ label, value, onChange, onCopy }: { label: string; value: string; onChange: (value: string) => void; onCopy: () => void }) {
  return <div className="draft-generated"><label>{label}<textarea value={value} onChange={(event) => onChange(event.target.value)} /></label><div className="draft-actions"><span className="draft-status">Draft only · Not submitted</span><button className="copy-button" type="button" onClick={onCopy}>Copy draft</button></div></div>;
}
