"use client";

// Add vehicles and edit records (issue #42). All writes go through the backend REST API,
// which validates them, guards against stale edits, and appends a change-log entry.

import { FormEvent, useState } from "react";
import { formatDateTime, useTimeZone } from "./display-prefs";

export type EditableHistoryEvent = { date: string; name: string; detail: string; mileage: string; source?: string; edited?: boolean };
export type EditableRecommendation = { name: string; status: string; kind: string; text: string; evidence: string; rule: string; safety?: boolean; source?: string; index?: number };
export type ChangeLogEntry = { at: string; action: string; actor: string; summary: string };
export type EditableVehicle = {
  serial: string;
  make: string;
  model: string;
  year: number;
  mileage: number | null;
  history: EditableHistoryEvent[];
  recs: EditableRecommendation[];
  changeLog?: ChangeLogEntry[];
};

const REC_STATUSES = ["Due", "Coming up", "Advisor verification", "Not yet due"] as const;

/** Send JSON to the local backend and return parsed JSON, or throw a readable error. */
export async function sendJson<T>(method: "POST" | "PATCH" | "PUT" | "DELETE", url: string, body?: unknown): Promise<T> {
  const response = await fetch(url, {
    method,
    headers: { Accept: "application/json", ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let data: { detail?: unknown } | null = null;
  try {
    data = JSON.parse(text) as { detail?: unknown };
  } catch {
    data = null;
  }
  if (!response.ok) {
    const detail = data?.detail;
    const message = typeof detail === "string" ? detail : Array.isArray(detail) ? "Check the highlighted fields: some values are missing or invalid." : "";
    throw new Error(message || `The save failed (HTTP ${response.status}). Check that the backend is running.`);
  }
  if (data === null) throw new Error("The backend returned an unreadable response.");
  return data as T;
}

const todayIso = () => {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
};
const vehiclePath = (serial: string) => `/api/copilot/vehicles/${encodeURIComponent(serial)}`;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "Apr 18, 2026" -> "2026-04-18" for a date input; empty if unreadable. */
function historyDateToIso(value: string): string {
  const match = /^([A-Za-z]{3}) (\d{1,2}), (\d{4})$/.exec(value.trim());
  if (!match) return "";
  const month = MONTHS.indexOf(match[1]) + 1;
  return month ? `${match[3]}-${String(month).padStart(2, "0")}-${match[2].padStart(2, "0")}` : "";
}

function milesFromText(value: string): string {
  const digits = value.replace(/\D/g, "");
  return digits;
}

function FormError({ message }: { message: string }) {
  return message ? <p className="ai-error" role="alert">{message}</p> : null;
}

// ---- Add vehicle ----

export function AddVehicleForm({ initialSerial = "", onCreated, onCancel }: { initialSerial?: string; onCreated: (vehicle: EditableVehicle) => void; onCancel: () => void }) {
  const [form, setForm] = useState({ serial: initialSerial, make: "", model: "", year: String(new Date().getFullYear()), mileage: "", mileageDate: todayIso() });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const created = await sendJson<EditableVehicle>("POST", "/api/copilot/vehicles", {
        serial: form.serial, make: form.make, model: form.model, year: Number(form.year),
        mileage: form.mileage === "" ? null : Number(form.mileage),
        mileageDate: form.mileage === "" ? null : form.mileageDate,
      });
      onCreated(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add the vehicle.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="service-form edit-form" onSubmit={submit} aria-label="Add a vehicle">
      <h4>Add a vehicle</h4>
      <div className="service-form-grid">
        <label>Serial number<input required minLength={3} maxLength={32} pattern="[A-Za-z0-9][A-Za-z0-9-]{1,30}[A-Za-z0-9]" title="3–32 letters, digits, or hyphens" value={form.serial} onChange={(e) => setForm({ ...form, serial: e.target.value })} placeholder="e.g. NS-3001" /></label>
        <label>Make<input required maxLength={40} value={form.make} onChange={(e) => setForm({ ...form, make: e.target.value })} placeholder="e.g. Northstar" /></label>
        <label>Model<input required maxLength={40} value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} placeholder="e.g. Alder" /></label>
        <label>Model year<input required type="number" min={1980} max={new Date().getFullYear() + 1} value={form.year} onChange={(e) => setForm({ ...form, year: e.target.value })} /></label>
        <label>Current mileage (optional)<input type="number" min={0} step={1} value={form.mileage} onChange={(e) => setForm({ ...form, mileage: e.target.value })} placeholder="Leave blank if unknown" /></label>
        {form.mileage !== "" && <label>Mileage read on<input type="date" required max={todayIso()} value={form.mileageDate} onChange={(e) => setForm({ ...form, mileageDate: e.target.value })} /></label>}
      </div>
      <p className="manual-mileage-note">Synthetic demo record. The vehicle starts with no service history, so recommendations stay paused until history is added. The addition is saved to the database and logged.</p>
      <FormError message={error} />
      <div className="service-form-actions"><button className="copy-button" type="button" onClick={onCancel} disabled={saving}>Cancel</button><button className="primary-button" type="submit" disabled={saving}>{saving ? "Saving…" : "Add vehicle"}</button></div>
    </form>
  );
}

// ---- Vehicle details ----

export function VehicleDetailsForm({ vehicle, onSaved, onCancel }: { vehicle: EditableVehicle; onSaved: (vehicle: EditableVehicle) => void; onCancel: () => void }) {
  const [form, setForm] = useState({ serial: vehicle.serial, make: vehicle.make, model: vehicle.model, year: String(vehicle.year) });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const renamed = form.serial.trim().toUpperCase() !== vehicle.serial;
      const updated = await sendJson<EditableVehicle>("PATCH", vehiclePath(vehicle.serial), {
        make: form.make, model: form.model, year: Number(form.year), newSerial: renamed ? form.serial : null,
      });
      onSaved(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the vehicle details.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="service-form edit-form" onSubmit={submit} aria-label="Edit vehicle details">
      <h4>Edit vehicle details</h4>
      <div className="service-form-grid">
        <label>Serial number<input required minLength={3} maxLength={32} pattern="[A-Za-z0-9][A-Za-z0-9-]{1,30}[A-Za-z0-9]" title="3–32 letters, digits, or hyphens" value={form.serial} onChange={(e) => setForm({ ...form, serial: e.target.value })} /></label>
        <label>Make<input required maxLength={40} value={form.make} onChange={(e) => setForm({ ...form, make: e.target.value })} /></label>
        <label>Model<input required maxLength={40} value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} /></label>
        <label>Model year<input required type="number" min={1980} max={new Date().getFullYear() + 1} value={form.year} onChange={(e) => setForm({ ...form, year: e.target.value })} /></label>
      </div>
      <p className="manual-mileage-note">Changing the serial moves the whole record to the new serial. Use the mileage form to change mileage.</p>
      <FormError message={error} />
      <div className="service-form-actions"><button className="copy-button" type="button" onClick={onCancel} disabled={saving}>Cancel</button><button className="primary-button" type="submit" disabled={saving}>{saving ? "Saving…" : "Save details"}</button></div>
    </form>
  );
}

// ---- Service history rows ----

export function HistoryRows({ vehicle, onSaved }: { vehicle: EditableVehicle; onSaved: (vehicle: EditableVehicle) => void }) {
  const [editing, setEditing] = useState<number | null>(null);
  const [form, setForm] = useState({ serviceDate: "", name: "", detail: "", mileage: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ index: number; message: string } | null>(null);

  function startEdit(index: number) {
    const event = vehicle.history[index];
    setForm({ serviceDate: historyDateToIso(event.date) || todayIso(), name: event.name, detail: event.detail, mileage: milesFromText(event.mileage) });
    setEditing(index);
    setError(null);
  }

  async function save(event: FormEvent<HTMLFormElement>, index: number) {
    event.preventDefault();
    const entry = vehicle.history[index];
    setBusy(true);
    setError(null);
    try {
      const updated = await sendJson<EditableVehicle>("PUT", `${vehiclePath(vehicle.serial)}/history/${index}`, {
        expected: { date: entry.date, name: entry.name },
        serviceDate: form.serviceDate, name: form.name, detail: form.detail,
        mileage: form.mileage === "" ? null : Number(form.mileage),
      });
      setEditing(null);
      onSaved(updated);
    } catch (err) {
      setError({ index, message: err instanceof Error ? err.message : "Could not save the history entry." });
    } finally {
      setBusy(false);
    }
  }

  if (vehicle.history.length === 0) return <div className="evidence">No service history recorded yet. Use “+ Record service” to add the first entry.</div>;

  return (
    <>
      {vehicle.history.map((event, index) => (
        <div key={`${event.date}-${event.name}-${index}`}>
          {editing === index ? (
            <form className="service-form edit-form" onSubmit={(e) => void save(e, index)} aria-label={`Edit history entry ${event.name}`}>
              <h4>Edit history entry</h4>
              <div className="service-form-grid">
                <label>Service<input required maxLength={80} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
                <label>Date<input required type="date" max={todayIso()} value={form.serviceDate} onChange={(e) => setForm({ ...form, serviceDate: e.target.value })} /></label>
                <label>Odometer (mi)<input type="number" min={0} step={1} value={form.mileage} onChange={(e) => setForm({ ...form, mileage: e.target.value })} placeholder="Blank if not recorded" /></label>
                <label className="service-form-note">Detail<input maxLength={200} value={form.detail} onChange={(e) => setForm({ ...form, detail: e.target.value })} /></label>
              </div>
              {error?.index === index && <FormError message={error.message} />}
              <div className="service-form-actions"><button className="copy-button" type="button" onClick={() => setEditing(null)} disabled={busy}>Cancel</button><button className="primary-button" type="submit" disabled={busy}>{busy ? "Saving…" : "Save entry"}</button></div>
            </form>
          ) : (
            <div className="history-row history-row-editable">
              <span className="history-date">{event.date}</span>
              <span className="history-name">{event.name}{event.edited && <span className="edited-tag">edited</span>}<span className="history-detail">{event.detail}</span></span>
              <span className="history-mileage">{event.mileage}</span>
              <span className="row-actions">
                <button className="copy-button" type="button" onClick={() => startEdit(index)} aria-label={`Edit ${event.name} on ${event.date}`}>Edit</button>
              </span>
              {error?.index === index && editing !== index && <span className="row-error"><FormError message={error.message} /></span>}
            </div>
          )}
        </div>
      ))}
    </>
  );
}

// ---- Recommendations ----

type RecForm = { name: string; status: string; text: string; evidence: string; safety: boolean };

function RecommendationForm({ title, initial, busy, error, onSubmit, onCancel }: { title: string; initial: RecForm; busy: boolean; error: string; onSubmit: (form: RecForm) => void; onCancel: () => void }) {
  const [form, setForm] = useState(initial);
  return (
    <form className="service-form edit-form" onSubmit={(e) => { e.preventDefault(); onSubmit(form); }} aria-label={title}>
      <h4>{title}</h4>
      <div className="service-form-grid">
        <label>Recommendation<input required maxLength={80} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. Cabin air filter" /></label>
        <label>Status<select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>{REC_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}</select></label>
        <label className="service-form-note">Explanation<input required maxLength={400} value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} placeholder="What the advisor recommends and why" /></label>
        <label className="service-form-note">Evidence<input required maxLength={400} value={form.evidence} onChange={(e) => setForm({ ...form, evidence: e.target.value })} placeholder="e.g. Visual inspection on today's visit" /></label>
        <label className="checkbox-label"><input type="checkbox" checked={form.safety} onChange={(e) => setForm({ ...form, safety: e.target.checked })} /> Safety-related (shown as a verification prompt)</label>
      </div>
      <p className="manual-mileage-note">Saved as an <strong>Advisor-entered</strong> recommendation with your evidence. It is not from the demo schedule and is logged in the change log.</p>
      <FormError message={error} />
      <div className="service-form-actions"><button className="copy-button" type="button" onClick={onCancel} disabled={busy}>Cancel</button><button className="primary-button" type="submit" disabled={busy}>{busy ? "Saving…" : "Save recommendation"}</button></div>
    </form>
  );
}

export function useRecommendationEditor(vehicle: EditableVehicle | null, onSaved: (vehicle: EditableVehicle) => void) {
  const [mode, setMode] = useState<{ kind: "add" } | { kind: "edit"; index: number } | { kind: "remove"; index: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function run(action: () => Promise<EditableVehicle>) {
    setBusy(true);
    setError("");
    try {
      onSaved(await action());
      setMode(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the recommendation.");
    } finally {
      setBusy(false);
    }
  }

  function addForm() {
    if (!vehicle || mode?.kind !== "add") return null;
    return <RecommendationForm title="Add a recommendation" initial={{ name: "", status: "Due", text: "", evidence: "", safety: false }} busy={busy} error={error}
      onCancel={() => { setMode(null); setError(""); }}
      onSubmit={(form) => void run(() => sendJson("POST", `${vehiclePath(vehicle.serial)}/recommendations`, form))} />;
  }

  function editorFor(index: number) {
    if (!vehicle) return null;
    const rec = vehicle.recs.find((item) => item.index === index) ?? (vehicle.recs.every((item) => item.index === undefined) ? vehicle.recs[index] : undefined);
    if (!rec) return null;
    if (mode?.kind === "edit" && mode.index === index) {
      return <RecommendationForm title={`Edit “${rec.name}”`} initial={{ name: rec.name, status: REC_STATUSES.includes(rec.status as (typeof REC_STATUSES)[number]) ? rec.status : "Due", text: rec.text, evidence: rec.evidence, safety: Boolean(rec.safety) }} busy={busy} error={error}
        onCancel={() => { setMode(null); setError(""); }}
        onSubmit={(form) => void run(() => sendJson("PUT", `${vehiclePath(vehicle.serial)}/recommendations/${index}`, { ...form, expectedName: rec.name }))} />;
    }
    if (mode?.kind === "remove" && mode.index === index) {
      return (
        <div className="inline-confirm" role="alertdialog" aria-label={`Remove ${rec.name}`}>
          <span>Remove “{rec.name}” from this record?</span>
          <button className="copy-button danger-button" type="button" disabled={busy} onClick={() => void run(() => sendJson("DELETE", `${vehiclePath(vehicle.serial)}/recommendations/${index}?${new URLSearchParams({ expectedName: rec.name })}`))}>Yes, remove</button>
          <button className="copy-button" type="button" disabled={busy} onClick={() => { setMode(null); setError(""); }}>Cancel</button>
          <FormError message={error} />
        </div>
      );
    }
    return null;
  }

  return {
    mode,
    startAdd: () => { setMode({ kind: "add" }); setError(""); },
    startEdit: (index: number) => { setMode({ kind: "edit", index }); setError(""); },
    startRemove: (index: number) => { setMode({ kind: "remove", index }); setError(""); },
    reset: () => { setMode(null); setError(""); },
    addForm,
    editorFor,
  };
}

// ---- Change log ----

export function ChangeLog({ entries }: { entries?: ChangeLogEntry[] }) {
  const [showAll, setShowAll] = useState(false);
  const { timeZone } = useTimeZone();
  const newestFirst = [...(entries ?? [])].reverse();
  const visible = showAll ? newestFirst : newestFirst.slice(0, 5);
  return (
    <section className="panel change-log" aria-labelledby="change-log-title">
      <div className="panel-title-row"><div><h3 id="change-log-title">Change log</h3><div className="panel-subtitle">Edits saved through this app</div></div><span className="draft-type">{newestFirst.length} {newestFirst.length === 1 ? "change" : "changes"}</span></div>
      {newestFirst.length === 0 ? <p className="summary-muted">No changes have been saved for this vehicle yet.</p> : (
        <ol className="change-log-list">
          {visible.map((entry, index) => (
            <li key={`${entry.at}-${index}`}><time dateTime={entry.at}>{formatDateTime(entry.at, timeZone)}</time><span>{entry.summary}</span><small>{entry.actor}</small></li>
          ))}
        </ol>
      )}
      {newestFirst.length > 5 && <button className="link-button" type="button" onClick={() => setShowAll(!showAll)}>{showAll ? "Show latest 5" : `Show all ${newestFirst.length}`}</button>}
    </section>
  );
}
