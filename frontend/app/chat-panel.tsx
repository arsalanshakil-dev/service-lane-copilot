"use client";

import { FormEvent, useEffect, useState } from "react";

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  tools?: string[];
};

type ModelsResponse = {
  local_only: boolean;
  models: string[];
};

type ChatResponse = {
  reply: string;
  tools_used: string[];
  model: string;
};

const HISTORY_LIMIT = 12;

export default function ChatPanel() {
  const [open, setOpen] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [refreshModels, setRefreshModels] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function loadModels() {
      setError("");
      try {
        const response = await fetch("/api/copilot/chat/models", {
          headers: { Accept: "application/json" },
        });
        const data = (await response.json()) as ModelsResponse & { detail?: string };
        if (!response.ok || !data.local_only) {
          throw new Error(data.detail ?? "Could not connect to local Ollama.");
        }
        if (!cancelled) {
          setModels(data.models);
          setModel((current) => (data.models.includes(current) ? current : data.models[0] ?? ""));
          if (data.models.length === 0) {
            setError("No local Ollama models found. Install a model, then refresh the list.");
          }
        }
      } catch (reason) {
        if (!cancelled) {
          setModels([]);
          setModel("");
          setError(reason instanceof Error ? reason.message : "Could not connect to local Ollama.");
        }
      }
    }
    void loadModels();
    return () => {
      cancelled = true;
    };
  }, [refreshModels]);

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = input.trim();
    if (!text || !model || loading) return;

    const userMessage: ChatMessage = { role: "user", content: text };
    const priorMessages = messages.slice(-HISTORY_LIMIT);
    setMessages((current) => [...current, userMessage]);
    setInput("");
    setError("");
    setLoading(true);
    try {
      const response = await fetch("/api/copilot/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          model,
          message: text,
          history: priorMessages.map(({ role, content }) => ({ role, content })),
        }),
      });
      const data = (await response.json()) as ChatResponse & { detail?: string };
      if (!response.ok) {
        throw new Error(data.detail ?? "The local assistant could not complete this request.");
      }
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: data.reply || "The local model returned an empty response. Try a tool-focused question.",
          tools: data.tools_used,
        },
      ]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The local assistant could not complete this request.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="chat-assistant">
      <button
        className="chat-launcher"
        type="button"
        aria-expanded={open}
        aria-controls="copilot-chat-panel"
        onClick={() => setOpen((current) => !current)}
      >
        <span aria-hidden="true">✦</span> {open ? "Close assistant" : "Ask Copilot"}
      </button>
      {open && (
        <section
          id="copilot-chat-panel"
          className="chat-panel"
          role="dialog"
          aria-modal="false"
          aria-labelledby="chat-panel-title"
        >
          <header className="chat-panel-header">
            <div>
              <h2 id="chat-panel-title">Service Lane Assistant</h2>
              <p>Local Ollama · Synthetic records only</p>
            </div>
            <div className="chat-header-actions">
              <button type="button" className="chat-icon-button" onClick={() => setMessages([])} aria-label="Clear chat">↺</button>
              <button type="button" className="chat-icon-button" onClick={() => setOpen(false)} aria-label="Close chat">×</button>
            </div>
          </header>
          <div className="chat-model-row">
            <label htmlFor="chat-model">Local model</label>
            <select id="chat-model" value={model} onChange={(event) => setModel(event.target.value)} disabled={models.length === 0 || loading}>
              {models.length === 0 ? <option value="">No local models</option> : models.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
            <button type="button" className="chat-refresh" onClick={() => setRefreshModels((value) => value + 1)} disabled={loading} aria-label="Refresh local model list">↻</button>
          </div>
          <div className="chat-privacy-note">Messages and MCP requests stay on this computer. This assistant can read records and prepare drafts; it cannot send or update anything.</div>
          <div className="chat-messages" aria-live="polite" aria-relevant="additions text">
            {messages.length === 0 && (
              <div className="chat-empty">
                <strong>What would you like to prepare?</strong>
                <p>Ask about a vehicle, review its service history, or prepare an unsent customer draft.</p>
                <span>Try: “Look up NS-2048 and explain what may be coming up.”</span>
              </div>
            )}
            {messages.map((item, index) => (
              <article className={`chat-message ${item.role}`} key={`${item.role}-${index}`}>
                <span className="chat-role">{item.role === "user" ? "You" : "Copilot"}</span>
                <p>{item.content}</p>
                {item.tools && item.tools.length > 0 && <small>Used MCP: {item.tools.join(", ")}</small>}
              </article>
            ))}
            {loading && <div className="chat-working" role="status">Checking local records…</div>}
          </div>
          {error && <div className="chat-error" role="alert">{error}</div>}
          <form className="chat-compose" onSubmit={sendMessage}>
            <label className="sr-only" htmlFor="chat-message">Message the Service Lane Assistant</label>
            <textarea
              id="chat-message"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Ask about a vehicle or draft…"
              rows={2}
              maxLength={4_000}
              disabled={loading || !model}
            />
            <button type="submit" disabled={loading || !model || !input.trim()}>{loading ? "Working…" : "Send"}</button>
          </form>
        </section>
      )}
    </div>
  );
}
