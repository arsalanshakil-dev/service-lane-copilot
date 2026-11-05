"use client";

import { FormEvent, useState } from "react";
import { useAiModel } from "./ai-model";

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  tools?: string[];
};

type ChatResponse = {
  reply: string;
  tools_used: string[];
  model: string;
};

const HISTORY_LIMIT = 12;

export default function ChatPanel() {
  const [open, setOpen] = useState(false);
  // The model is chosen once in Settings and shared by every AI feature (issue #40).
  const { model, error: modelError, loading: modelsLoading } = useAiModel();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

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
      const responseText = await response.text();
      let data: ChatResponse & { detail?: string };
      try {
        data = JSON.parse(responseText) as ChatResponse & { detail?: string };
      } catch {
        const genericError = /internal server error/i.test(responseText);
        data = {
          detail: genericError
            ? `The local chat service failed (HTTP ${response.status}). Check the backend terminal for the error and confirm Ollama is running.`
            : responseText.slice(0, 300),
        } as ChatResponse & { detail?: string };
      }
      if (!response.ok) {
        throw new Error(data.detail || `The local assistant request failed (HTTP ${response.status}). Check that the backend and Ollama are running.`);
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
            <span className="chat-model-label">Model</span>
            <strong className="chat-model-name">{modelsLoading ? "Loading…" : model || "None available"}</strong>
            <a className="chat-settings-link" href="#settings" onClick={() => setOpen(false)}>Change in Settings</a>
          </div>
          {!modelsLoading && modelError && <div className="chat-error" role="alert">{modelError} Open Settings to check the model.</div>}
          <div className="chat-privacy-note">Messages and MCP requests stay on this computer. This assistant can read records and prepare drafts; it cannot send or update anything.</div>
          <div className="chat-messages" aria-live="polite" aria-relevant="additions text">
            {messages.length === 0 && (
              <div className="chat-empty">
                <strong>What would you like to prepare?</strong>
                <p>Ask about a vehicle, review its service history, or prepare an unsent customer draft. This assistant answers dealership service questions only, not general questions.</p>
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
              placeholder="Ask about a vehicle, its service, or a draft…"
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
