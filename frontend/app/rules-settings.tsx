"use client";

// Settings → Maintenance rules (issue #47). Rules are stored in the database for the whole app;
// recommendations are computed from them on every read. Every change is logged per rule.

import { FormEvent, useEffect, useState } from "react";
import { formatDateTime, useTimeZone } from "./display-prefs";
import { sendJson, type ChangeLogEntry } from "./record-editors";

type Rule = {
  id: string;
  service_name: string;
  coming_up_miles: number;
  due_miles: number;
  safety: boolean;
  enabled: boolean;
  updated_at: string;
  change_log?: ChangeLogEntry[];
};

type RulesResponse = { status: "active" | "unavailable"; detail?: string; rules: Rule[] };
type RuleForm = { serviceName: string; comingUpMiles: string; dueMiles: string; safety: boolean; enabled: boolean };

const miles = (value: number) => `${value.toLocaleString()} mi`;

function RuleFormFields({ form, onChange }: { form: RuleForm; onChange: (form: RuleForm) => void }) {
  return (
    <div className="service-form-grid">
      <label>Service<input required maxLength={80} value={form.serviceName} onChange={(e) => onChange({ ...form, serviceName: e.target.value })} placeholder="e.g. Coolant flush" /></label>
      <label>Coming up from (mi)<input required type="number" min={0} max={200000} step={1} value={form.comingUpMiles} onChange={(e) => onChange({ ...form, comingUpMiles: e.target.value })} /></label>
      <label>Due at (mi)<input required type="number" min={1} max={200000} step={1} value={form.dueMiles} onChange={(e) => onChange({ ...form, dueMiles: e.target.value })} /></label>
      <label className="checkbox-label"><input type="checkbox" checked={form.safety} onChange={(e) => onChange({ ...form, safety: e.target.checked })} /> Safety-related (shown as Advisor verification, not a diagnosis)</label>
      <label className="checkbox-label"><input type="checkbox" checked={form.enabled} onChange={(e) => onChange({ ...form, enabled: e.target.checked })} /> Enabled</label>
    </div>
  );
}

export function MaintenanceRulesPanel() {
  const { timeZone } = useTimeZone();
  const [data, setData] = useState<RulesResponse | null>(null);
  const [loadError, setLoadError] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [openLog, setOpenLog] = useState<string | null>(null);
  const [form, setForm] = useState<RuleForm>({ serviceName: "", comingUpMiles: "", dueMiles: "", safety: false, enabled: true });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/copilot/rules", { headers: { Accept: "application/json" } })
      .then((response) => response.json().catch(() => null))
      .then((body: RulesResponse | null) => {
        if (cancelled) return;
        if (!body || !Array.isArray(body.rules)) throw new Error("Could not load maintenance rules. Check that the backend is running.");
        setData(body);
        setLoadError("");
      })
      .catch((err) => !cancelled && setLoadError(err instanceof Error ? err.message : "Could not load maintenance rules."));
    return () => {
      cancelled = true;
    };
  }, [reload]);

  function startEdit(rule: Rule) {
    setForm({ serviceName: rule.service_name, comingUpMiles: String(rule.coming_up_miles), dueMiles: String(rule.due_miles), safety: rule.safety, enabled: rule.enabled });
    setEditing(rule.id);
    setAdding(false);
    setError("");
  }

  function startAdd() {
    setForm({ serviceName: "", comingUpMiles: "", dueMiles: "", safety: false, enabled: true });
    setAdding(true);
    setEditing(null);
    setError("");
  }

  async function submit(event: FormEvent<HTMLFormElement>, rule?: Rule) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body = { serviceName: form.serviceName, comingUpMiles: Number(form.comingUpMiles), dueMiles: Number(form.dueMiles), safety: form.safety };
      const result = rule
        ? await sendJson<Rule>("PUT", `/api/copilot/rules/${encodeURIComponent(rule.id)}`, { ...body, enabled: form.enabled, expectedUpdatedAt: rule.updated_at })
        : await sendJson<Rule>("POST", "/api/copilot/rules", body);
      setSaved(`Saved “${result.service_name}”. Recommendations use the new rule on the next lookup.`);
      setEditing(null);
      setAdding(false);
      setReload((n) => n + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The rule was not saved.");
    } finally {
      setBusy(false);
    }
  }

  const header = <div className="panel-title-row"><div><h3>Maintenance rules</h3><div className="panel-subtitle">Demo rules — not manufacturer schedules. Miles since the last recorded service of that type.</div></div><span className="draft-type">ALL USERS</span></div>;

  if (loadError) return <div className="panel settings-panel">{header}<p className="ai-error" role="alert">{loadError}</p></div>;
  if (!data) return <div className="panel settings-panel">{header}<p className="summary-muted">Loading rules…</p></div>;
  if (data.status === "unavailable") {
    return (
      <div className="panel settings-panel">
        {header}
        <div className="warning-banner"><b>!</b><span>Rules are not set up in the database yet, so stored recommendations are shown. Open your Supabase project → SQL Editor, paste <code>supabase/migrations/20261106000100_create_service_rules.sql</code>, and click Run. Then reload this page.</span></div>
        <button className="copy-button" type="button" onClick={() => setReload((n) => n + 1)}>Check again</button>
      </div>
    );
  }

  return (
    <div className="panel settings-panel rules-panel">
      {header}
      {saved && <p className="settings-status" aria-live="polite">{saved}</p>}
      <div className="records-table-wrap">
        <table className="records-table rules-table">
          <thead><tr><th scope="col">Service</th><th scope="col">Coming up from</th><th scope="col">Due at</th><th scope="col">Type</th><th scope="col">Status</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>
            {data.rules.map((rule) => (
              <tr key={rule.id} className={rule.enabled ? "" : "rule-disabled"}>
                <td>{rule.service_name}</td>
                <td>{miles(rule.coming_up_miles)}</td>
                <td>{miles(rule.due_miles)}</td>
                <td>{rule.safety ? "Safety (verify)" : "Standard"}</td>
                <td>{rule.enabled ? "Enabled" : "Disabled"}</td>
                <td className="row-actions"><button className="copy-button" type="button" onClick={() => startEdit(rule)}>Edit</button><button className="copy-button" type="button" onClick={() => setOpenLog(openLog === rule.id ? null : rule.id)} aria-expanded={openLog === rule.id}>History</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.rules.map((rule) => editing === rule.id && (
        <form key={`edit-${rule.id}`} className="service-form edit-form" onSubmit={(e) => void submit(e, rule)} aria-label={`Edit rule ${rule.service_name}`}>
          <h4>Edit rule “{rule.service_name}”</h4>
          <RuleFormFields form={form} onChange={setForm} />
          {error && <p className="ai-error" role="alert">{error}</p>}
          <div className="service-form-actions"><button className="copy-button" type="button" onClick={() => setEditing(null)} disabled={busy}>Cancel</button><button className="primary-button" type="submit" disabled={busy}>{busy ? "Saving…" : "Save rule"}</button></div>
        </form>
      ))}
      {data.rules.map((rule) => openLog === rule.id && (
        <div key={`log-${rule.id}`} className="service-form">
          <h4>Change history · {rule.service_name}</h4>
          <ol className="change-log-list">{[...(rule.change_log ?? [])].reverse().map((entry, index) => <li key={index}>{entry.at && <time dateTime={entry.at}>{formatDateTime(entry.at, timeZone)}</time>}<span>{entry.summary}</span><small>{entry.actor}</small></li>)}</ol>
        </div>
      ))}
      {adding ? (
        <form className="service-form edit-form" onSubmit={(e) => void submit(e)} aria-label="Add a maintenance rule">
          <h4>Add a maintenance rule</h4>
          <RuleFormFields form={form} onChange={setForm} />
          {error && <p className="ai-error" role="alert">{error}</p>}
          <div className="service-form-actions"><button className="copy-button" type="button" onClick={() => setAdding(false)} disabled={busy}>Cancel</button><button className="primary-button" type="submit" disabled={busy}>{busy ? "Saving…" : "Add rule"}</button></div>
        </form>
      ) : <div className="rules-actions"><button className="copy-button" type="button" onClick={startAdd}>+ Add rule</button></div>}
      <p className="disclaimer">Due / Coming up is worked out from each vehicle's most recent recorded service of the same type and its current mileage. Services never recorded on a vehicle are not flagged. Rules cannot be deleted; disable them instead.</p>
    </div>
  );
}
