"use client";

import { FormEvent, useState } from "react";
import { useAiModel } from "./ai-model";
import { sendJson } from "./record-editors";

// Issue #44: the chat never saves changes itself. Write requests come back as proposals that
// the advisor applies or discards here; applying calls the backend once and is logged.
type Proposal = { id: string; tool: string; summary: string; arguments: Record<string, unknown> };
type ProposalState = { status: "pending" | "applying" | "saved" | "discarded" | "error"; message?: string };
export const RECORD_CHANGED_EVENT = "service-lane-record-changed";

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  tools?: string[];
  proposals?: Proposal[];
};

type ChatResponse = {
  reply: string;
  tools_used: string[];
  model: string;
  proposals?: Proposal[];
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
  const [proposalStates, setProposalStates] = useState<Record<string, ProposalState>>({});

  function setProposal(id: string, state: ProposalState) {
    setProposalStates((current) => ({ ...current, [id]: state }));
  }

  async function applyProposal(proposal: Proposal) {
    setProposal(proposal.id, { status: "applying" });
    try {
      const result = await sendJson<{ saved: boolean; serial: string; change?: { summary: string } }>("POST", `/api/copilot/chat/proposals/${proposal.id}/apply`);
      setProposal(proposal.id, { status: "saved", message: result.change?.summary ?? "Saved." });
      // Let an open vehicle view refresh itself.
      window.dispatchEvent(new CustomEvent(RECORD_CHANGED_EVENT, { detail: { serial: result.serial, previousSerial: String(proposal.arguments.serial ?? "").toUpperCase() } }));
    } catch (reason) {
      setProposal(proposal.id, { status: "error", message: reason instanceof Error ? reason.message : "The change was not saved." });
    }
  }

  async function discardProposal(proposal: Proposal) {
    try {
      await sendJson("DELETE", `/api/copilot/chat/proposals/${proposal.id}`);
    } catch {
      // Already used or expired: either way nothing will be saved.
    }
    setProposal(proposal.id, { status: "discarded" });
  }

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
          proposals: data.proposals ?? [],
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
            <a className="copy-button chat-settings-link" href="#settings" onClick={() => setOpen(false)}>Change in Settings</a>
          </div>
          {!modelsLoading && modelError && <div className="chat-error" role="alert">{modelError} Open Settings to check the model.</div>}
          <div className="chat-privacy-note">Messages and MCP requests stay on this computer. This assistant can read records, prepare drafts, and propose record changes that are saved only when you click Apply. It never sends anything.</div>
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
                {item.role === "assistant" ? <ChatText text={item.content} /> : <p>{item.content}</p>}
                {item.tools && item.tools.length > 0 && <small>Used MCP: {item.tools.join(", ")}</small>}
                {item.proposals?.map((proposal) => <ProposalCard key={proposal.id} proposal={proposal} state={proposalStates[proposal.id]} onApply={() => void applyProposal(proposal)} onDiscard={() => void discardProposal(proposal)} />)}
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

function ProposalCard({ proposal, state, onApply, onDiscard }: { proposal: Proposal; state?: ProposalState; onApply: () => void; onDiscard: () => void }) {
  const status = state?.status ?? "pending";
  return (
    <div className={`proposal-card ${status}`} role="group" aria-label="Proposed record change">
      <strong>Proposed change · not saved yet</strong>
      <p>{proposal.summary}</p>
      {status === "pending" || status === "error" ? (
        <div className="proposal-actions">
          <button className="primary-button" type="button" onClick={onApply}>Apply change</button>
          <button className="copy-button" type="button" onClick={onDiscard}>Discard</button>
        </div>
      ) : null}
      {status === "applying" && <span className="proposal-status">Saving…</span>}
      {status === "saved" && <span className="proposal-status saved">✓ Saved and logged: {state?.message}</span>}
      {status === "discarded" && <span className="proposal-status">Discarded. Nothing was changed.</span>}
      {status === "error" && <span className="proposal-status error" role="alert">{state?.message}</span>}
    </div>
  );
}

/** Render **bold** spans in one line as React elements (never raw HTML). */
function inline(text: string, keyPrefix: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).filter(Boolean).map((part, index) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4
      ? <strong key={`${keyPrefix}-${index}`}>{part.slice(2, -2)}</strong>
      : <span key={`${keyPrefix}-${index}`}>{part}</span>,
  );
}

/**
 * Small, safe formatter for the local model's replies: paragraphs, "-", "*", or "1." bullet lists,
 * and **bold**. Model text is only ever rendered as text nodes, so it cannot inject markup.
 */
function ChatText({ text }: { text: string }) {
  const blocks: { kind: "p" | "ul" | "ol"; lines: string[] }[] = [];
  for (const raw of text.replace(/\r\n/g, "\n").split("\n")) {
    const line = raw.trim();
    if (!line) {
      blocks.push({ kind: "p", lines: [] });
      continue;
    }
    const bullet = /^[-*•]\s+(.*)$/.exec(line);
    const numbered = /^\d+[.)]\s+(.*)$/.exec(line);
    const kind = bullet ? "ul" : numbered ? "ol" : "p";
    const content = bullet?.[1] ?? numbered?.[1] ?? line.replace(/^#{1,6}\s+/, "");
    const last = blocks[blocks.length - 1];
    if (last && last.kind === kind && (kind !== "p" || last.lines.length > 0)) last.lines.push(content);
    else blocks.push({ kind, lines: [content] });
  }
  return (
    <div className="chat-text">
      {blocks.filter((block) => block.lines.length > 0).map((block, index) => {
        if (block.kind === "p") return <p key={index}>{block.lines.map((line, i) => <span key={i}>{i > 0 && <br />}{inline(line, `${index}-${i}`)}</span>)}</p>;
        const items = block.lines.map((line, i) => <li key={i}>{inline(line, `${index}-${i}`)}</li>);
        return block.kind === "ul" ? <ul key={index}>{items}</ul> : <ol key={index}>{items}</ol>;
      })}
    </div>
  );
}
