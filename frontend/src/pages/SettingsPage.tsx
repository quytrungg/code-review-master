import { useCallback, useEffect, useState } from "react";
import { Cpu, FlaskConical, Github, PlugZap, RefreshCw } from "lucide-react";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { LLMKeys, VersionControlKeys } from "@/components/KeyManager";
import { useSettings } from "@/context/SettingsContext";
import { api, ApiError } from "@/services/api";
import type {
  BetaFeature,
  ConnectionResult,
  LLMKey,
  LLMKeyCreate,
  VersionControlKey,
  VersionControlKeyCreate,
} from "@/types";

export function SettingsPage() {
  const { settings, apply, refresh } = useSettings();
  const [vcKeys, setVcKeys] = useState<VersionControlKey[]>([]);
  const [llmKeys, setLlmKeys] = useState<LLMKey[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState(false);
  const [results, setResults] = useState<ConnectionResult[]>([]);
  const [betaPending, setBetaPending] = useState<string | null>(null);

  const loadKeys = useCallback(async () => {
    setLoading(true);
    setError(null);
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
    // First key of a family becomes the active one, so setup never stalls on a second click.
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

  async function activateVersionControl(id: number) {
    apply(await api.updateSettings({ version_control_key_id: id }));
    await loadKeys();
  }

  async function activateLLM(id: number) {
    apply(await api.updateSettings({ llm_key_id: id }));
    await loadKeys();
  }

  async function deleteVersionControl(id: number) {
    await api.deleteVersionControlKey(id);
    await Promise.all([loadKeys(), refresh()]);
  }

  async function deleteLLM(id: number) {
    await api.deleteLLMKey(id);
    await Promise.all([loadKeys(), refresh()]);
  }

  async function testActive() {
    setTesting(true);
    setError(null);
    try {
      const response = await api.testConnection(["version_control", "llm"]);
      setResults(response.results);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Connection test failed");
    } finally {
      setTesting(false);
    }
  }

  // Beta toggles render from `beta_registry` and always send the full flag map, matching the
  // PUT contract's full-dict replace.
  async function toggleBeta(feature: BetaFeature) {
    if (!settings || betaPending) return;
    const flags: Record<string, boolean> = {};
    for (const entry of settings.beta_registry) {
      flags[entry.id] = settings.beta_features[entry.id] ?? false;
    }
    flags[feature.id] = !(flags[feature.id] ?? false);
    setBetaPending(feature.id);
    setError(null);
    try {
      apply(await api.setBetaFeatures(flags));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save the beta setting");
    } finally {
      setBetaPending(null);
    }
  }

  return (
    <div className="space-y-5">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-inkMuted">
          Credentials live in your local database, one row per provider, and are masked here. The
          active key of each family is what the next review uses.
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
          title="Version control"
          description="GitHub or GitLab. Reviews use the token for the host in the pull-request URL."
          action={
            <Button variant="secondary" size="sm" onClick={() => void loadKeys()} disabled={loading}>
              <RefreshCw className={loading ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} /> Refresh
            </Button>
          }
        />
        <CardBody>
          <VersionControlKeys
            keys={vcKeys}
            activeId={settings?.version_control_key_id ?? null}
            onActivate={activateVersionControl}
            onCreate={createVersionControl}
            onDelete={deleteVersionControl}
            onTest={(id) => api.testVersionControlKey(id)}
          />
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          icon={<Cpu className="h-4 w-4" />}
          title="Model providers"
          description="Claude, OpenAI/Codex, Ollama Cloud or a local Ollama daemon. Several can coexist."
        />
        <CardBody>
          <LLMKeys
            keys={llmKeys}
            activeId={settings?.llm_key_id ?? null}
            onActivate={activateLLM}
            onCreate={createLLM}
            onDelete={deleteLLM}
            onTest={(id) => api.testLLMKey(id)}
          />
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          icon={<PlugZap className="h-4 w-4" />}
          title="Active connections"
          description="Probe the two active keys against their providers."
          action={
            <Button size="sm" onClick={() => void testActive()} disabled={testing}>
              {testing ? "Testing…" : "Test connection"}
            </Button>
          }
        />
        <CardBody>
          {results.length === 0 ? (
            <p className="text-xs text-inkMuted">Nothing tested yet.</p>
          ) : (
            <ul className="space-y-1.5">
              {results.map((result) => (
                <li key={result.target} className="flex items-start gap-2 text-xs">
                  <span className={result.ok ? "text-success" : "text-danger"}>
                    {result.ok ? "✓" : "✕"}
                  </span>
                  <span className="text-inkMuted">
                    <span className="font-medium text-ink">
                      {result.target === "version_control" ? "Version control" : "Model provider"}
                    </span>{" "}
                    — {result.detail}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      {settings && settings.beta_registry.length > 0 ? (
        <Card>
          <CardHeader
            icon={<FlaskConical className="h-4 w-4" />}
            title="Beta features"
            description="Experiments still in development. Turn one on to try it; turn it off to return to the stable behaviour."
          />
          <CardBody>
            <ul className="space-y-3">
              {settings.beta_registry.map((feature) => {
                const enabled = settings.beta_features[feature.id] ?? false;
                const busy = betaPending === feature.id;
                return (
                  <li key={feature.id} className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-sm font-medium text-ink">{feature.label}</p>
                      <p className="text-xs text-inkMuted">{feature.description}</p>
                    </div>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={enabled}
                      aria-label={feature.label}
                      disabled={busy || betaPending !== null}
                      onClick={() => void toggleBeta(feature)}
                      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors ${
                        enabled
                          ? "border-success/50 bg-success/30"
                          : "border-inkMuted/30 bg-inkMuted/10"
                      }`}
                    >
                      <span
                        className={`inline-block h-3.5 w-3.5 rounded-full transition-transform ${
                          enabled ? "translate-x-[18px] bg-success" : "translate-x-[3px] bg-inkMuted"
                        }`}
                      />
                    </button>
                  </li>
                );
              })}
            </ul>
          </CardBody>
        </Card>
      ) : null}
    </div>
  );
}
