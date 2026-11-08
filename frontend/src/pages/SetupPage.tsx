import { useCallback, useEffect, useState } from "react";
import { ArrowRight, CheckCircle2, Cpu, Github } from "lucide-react";
import { Link } from "react-router-dom";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { LLMKeys, VersionControlKeys } from "@/components/KeyManager";
import { useSettings } from "@/context/SettingsContext";
import { api, ApiError } from "@/services/api";
import type { LLMKey, LLMKeyCreate, VersionControlKey, VersionControlKeyCreate } from "@/types";

/**
 * First-run guide: one key from each family, then the dashboard unlocks. It is the same component
 * the Settings page uses, so there is only one way to add a credential.
 */
export function SetupPage() {
  const { settings, apply, refresh } = useSettings();
  const [vcKeys, setVcKeys] = useState<VersionControlKey[]>([]);
  const [llmKeys, setLlmKeys] = useState<LLMKey[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const loadKeys = useCallback(async () => {
    setLoading(true);
    try {
      const [vc, llm] = await Promise.all([api.listVersionControlKeys(), api.listLLMKeys()]);
      setVcKeys(vc);
      setLlmKeys(llm);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load credentials");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadKeys();
  }, [loadKeys]);

  async function createVersionControl(payload: VersionControlKeyCreate) {
    const created = await api.createVersionControlKey(payload);
    const next =
      settings?.version_control_key_id == null
        ? await api.updateSettings({ version_control_key_id: created.id })
        : null;
    await loadKeys();
    if (next) apply(next);
  }

  async function createLLM(payload: LLMKeyCreate) {
    const created = await api.createLLMKey(payload);
    const next =
      settings?.llm_key_id == null ? await api.updateSettings({ llm_key_id: created.id }) : null;
    await loadKeys();
    if (next) apply(next);
  }

  const hasVersionControl = settings?.version_control_key_id != null;
  const hasModel = settings?.llm_key_id != null;
  const ready = hasVersionControl && hasModel;

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <header className="space-y-2">
        <p className="label-text">First run</p>
        <h1 className="text-2xl font-semibold tracking-tight">Connect a provider to get started</h1>
        <p className="text-sm text-inkMuted">
          Two credentials are needed: a token for the host your pull requests live on, and an API key
          for the model that reviews them. Both stay in your local database.
        </p>
      </header>

      {error ? (
        <p className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">
          {error}
        </p>
      ) : null}

      <Card>
        <CardHeader
          icon={<Github className="h-4 w-4" />}
          title="1 · Version control"
          description="GitHub token (repo scope) or a GitLab personal access token with `api` scope."
          action={
            hasVersionControl ? (
              <span className="inline-flex items-center gap-1 text-xs text-success">
                <CheckCircle2 className="h-3.5 w-3.5" /> Connected
              </span>
            ) : null
          }
        />
        <CardBody>
          <VersionControlKeys
            keys={vcKeys}
            activeId={settings?.version_control_key_id ?? null}
            onActivate={async (id) => {
              apply(await api.updateSettings({ version_control_key_id: id }));
              await loadKeys();
            }}
            onCreate={createVersionControl}
            onDelete={async (id) => {
              await api.deleteVersionControlKey(id);
              await Promise.all([loadKeys(), refresh()]);
            }}
            onTest={(id) => api.testVersionControlKey(id)}
          />
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          icon={<Cpu className="h-4 w-4" />}
          title="2 · Model provider"
          description="Ollama Cloud is the quickest start; Claude, OpenAI/Codex and a local daemon work too."
          action={
            hasModel ? (
              <span className="inline-flex items-center gap-1 text-xs text-success">
                <CheckCircle2 className="h-3.5 w-3.5" /> Connected
              </span>
            ) : null
          }
        />
        <CardBody>
          <LLMKeys
            keys={llmKeys}
            activeId={settings?.llm_key_id ?? null}
            onActivate={async (id) => {
              apply(await api.updateSettings({ llm_key_id: id }));
              await loadKeys();
            }}
            onCreate={createLLM}
            onDelete={async (id) => {
              await api.deleteLLMKey(id);
              await Promise.all([loadKeys(), refresh()]);
            }}
            onTest={(id) => api.testLLMKey(id)}
          />
        </CardBody>
      </Card>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-surface/60 px-4 py-3">
        <p className="text-xs text-inkMuted">
          {ready
            ? "Both credentials are active. Paste a pull-request URL on the dashboard to start."
            : loading
              ? "Loading…"
              : "Add one key from each family to unlock reviews."}
        </p>
        <Link
          to="/"
          aria-disabled={!ready}
          className={
            ready
              ? "inline-flex items-center gap-1.5 rounded-lg bg-accentStrong px-4 py-2 text-sm font-medium text-white"
              : "pointer-events-none inline-flex items-center gap-1.5 rounded-lg border border-border px-4 py-2 text-sm text-inkMuted opacity-60"
          }
        >
          Go to reviews <ArrowRight className="h-4 w-4" />
        </Link>
      </div>
    </div>
  );
}
