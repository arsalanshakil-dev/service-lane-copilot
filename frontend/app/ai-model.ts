"use client";

// One AI model for the whole app (issue #40). The choice is saved in this browser and
// shared by every AI feature: chat, drafts, AI suggestions, and record summaries.

import { useCallback, useEffect, useState } from "react";

export const AI_MODEL_STORAGE_KEY = "service-lane-ai-model";
const CHANGE_EVENT = "service-lane-ai-model-change";

/** Embedding-only Ollama models cannot write text, so they are never offered. */
export const isChatModel = (name: string) => !/(?:embed|embedding|all-minilm)/i.test(name);

function readSaved(): string {
  try {
    return window.localStorage.getItem(AI_MODEL_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

export type AiModelState = {
  models: string[];
  model: string;
  setModel: (name: string) => void;
  refresh: () => void;
  loading: boolean;
  error: string;
};

export function useAiModel(): AiModelState {
  const [models, setModels] = useState<string[]>([]);
  const [saved, setSaved] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshCount, setRefreshCount] = useState(0);

  useEffect(() => {
    setSaved(readSaved());
    const sync = () => setSaved(readSaved());
    const onStorage = (event: StorageEvent) => {
      if (event.key === AI_MODEL_STORAGE_KEY) sync();
    };
    window.addEventListener(CHANGE_EVENT, sync);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener(CHANGE_EVENT, sync);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const response = await fetch("/api/copilot/chat/models", { headers: { Accept: "application/json" } });
        const data = (await response.json().catch(() => ({}))) as { models?: string[]; detail?: string };
        if (!response.ok || !Array.isArray(data.models)) {
          throw new Error(data.detail ?? "Local Ollama or the backend is unavailable. Start them and refresh.");
        }
        const chatModels = data.models.filter(isChatModel);
        if (cancelled) return;
        setModels(chatModels);
        if (chatModels.length === 0) setError("No local Ollama chat model is installed. Install one, then refresh.");
      } catch (err) {
        if (!cancelled) {
          setModels([]);
          setError(err instanceof Error ? err.message : "Local Ollama is unavailable.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [refreshCount]);

  const setModel = useCallback((name: string) => {
    try {
      window.localStorage.setItem(AI_MODEL_STORAGE_KEY, name);
    } catch {
      // Storage can be unavailable (private mode); the choice still applies to this page view.
    }
    setSaved(name);
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }, []);

  const refresh = useCallback(() => setRefreshCount((count) => count + 1), []);

  // Use the saved model when it is installed; otherwise fall back to the first installed chat model.
  const model = models.includes(saved) ? saved : models[0] ?? "";
  return { models, model, setModel, refresh, loading, error };
}
