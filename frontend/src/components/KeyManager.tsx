import { useState } from "react";
import { AlertTriangle, Check, CheckCircle2, KeyRound, Loader2, Plus, Trash2, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input, Label, Select } from "@/components/ui/Input";
import { cn } from "@/lib/utils";
import type { KeyTestResult, LLMKey, LLMKeyCreate, VersionControlKey, VersionControlKeyCreate } from "@/types";

const PROVIDER_LABEL: Record<string, string> = {
  github: "GitHub",
  gitlab: "GitLab",
  claude: "Claude",
  openai: "OpenAI / Codex",
  ollama_cloud: "Ollama Cloud",
  ollama_local: "Ollama (local)",
};

const VCS_OPTIONS = [
  { value: "github", label: "GitHub", needsBaseUrl: false },
  { value: "gitlab", label: "GitLab", needsBaseUrl: true },
];

const LLM_OPTIONS = [
  { value: "claude", label: "Claude", needsSecret: true, needsModel: true },
  { value: "openai", label: "OpenAI / Codex", needsSecret: true, needsModel: true },
  { value: "ollama_cloud", label: "Ollama Cloud", needsSecret: true, needsModel: true },
  { value: "ollama_local", label: "Ollama (local)", needsSecret: false, needsModel: true },
];

function ErrorText({ children }: { children: string | null }) {
  if (!children) return null;
  return (
    <p className="flex items-start gap-1.5 text-xs text-danger">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {children}
    </p>
  );
}

function TestResult({ result }: { result?: KeyTestResult }) {
  if (!result) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-[11px]",
        result.ok ? "text-success" : "text-danger",
      )}
      title={result.detail}
    >
      {result.ok ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
      {result.detail}
    </span>
  );
}

interface RowProps {
  provider: string;
  secret: string | null;
  detail: string | null;
  active: boolean;
  result?: KeyTestResult;
  testing: boolean;
  onActivate: () => void;
  onTest: () => void;
  onDelete: () => void;
}

function KeyRow({ provider, secret, detail, active, result, testing, onActivate, onTest, onDelete }: RowProps) {
  return (
    <div
      className={cn(
        "rounded-lg border px-3 py-2.5",
        active ? "border-accent/50 bg-accent/5" : "border-border bg-surfaceMuted/30",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={active ? "accent" : "neutral"}>{PROVIDER_LABEL[provider] ?? provider}</Badge>
        <span className="font-mono text-xs text-inkMuted">{secret ?? "no secret stored"}</span>
        {detail ? <span className="text-[11px] text-inkMuted">{detail}</span> : null}
        {active ? (
          <Badge tone="success">
            <Check className="h-3 w-3" /> active
          </Badge>
        ) : null}
        <div className="ml-auto flex items-center gap-1.5">
          <TestResult result={result} />
          {active ? null : (
            <Button variant="secondary" size="sm" onClick={onActivate}>
              Use
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={onTest} disabled={testing}>
            {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null} Test
          </Button>
          <Button variant="danger" size="sm" onClick={onDelete} title="Delete this key">
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  );
}

export interface VersionControlKeysProps {
  keys: VersionControlKey[];
  activeId: number | null;
  onActivate: (id: number) => Promise<void>;
  onCreate: (payload: VersionControlKeyCreate) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  onTest: (id: number) => Promise<KeyTestResult>;
}

export function VersionControlKeys({
  keys,
  activeId,
  onActivate,
  onCreate,
  onDelete,
  onTest,
}: VersionControlKeysProps) {
  const [provider, setProvider] = useState("github");
  const [token, setToken] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<Record<number, KeyTestResult>>({});
  const [testing, setTesting] = useState<number | null>(null);

  const option = VCS_OPTIONS.find((item) => item.value === provider) ?? VCS_OPTIONS[0];

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await onCreate({
        provider: provider as VersionControlKeyCreate["provider"],
        token: token.trim(),
        base_url: option.needsBaseUrl && baseUrl.trim() ? baseUrl.trim() : null,
        label: label.trim() || null,
      });
      setToken("");
      setLabel("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the key");
    } finally {
      setBusy(false);
    }
  }

  async function runTest(id: number) {
    setTesting(id);
    try {
      const result = await onTest(id);
      setResults((current) => ({ ...current, [id]: result }));
    } catch (err) {
      setResults((current) => ({
        ...current,
        [id]: { ok: false, detail: err instanceof Error ? err.message : "Test failed", metadata: null },
      }));
    } finally {
      setTesting(null);
    }
  }

  return (
    <div className="space-y-3">
      {keys.length === 0 ? (
        <p className="text-xs text-inkMuted">No version-control token yet. Add one below.</p>
      ) : null}
      {keys.map((key) => (
        <KeyRow
          key={key.id}
          provider={key.provider}
          secret={key.token_masked}
          detail={[key.label, key.base_url].filter(Boolean).join(" · ") || null}
          active={key.id === activeId}
          result={results[key.id]}
          testing={testing === key.id}
          onActivate={() => void onActivate(key.id)}
          onTest={() => void runTest(key.id)}
          onDelete={() => void onDelete(key.id)}
        />
      ))}

      <div className="rounded-lg border border-dashed border-border p-3">
        <div className="flex flex-wrap items-end gap-2">
          <div className="w-32 space-y-1">
            <Label>Provider</Label>
            <Select value={provider} onChange={(event) => setProvider(event.target.value)}>
              {VCS_OPTIONS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </Select>
          </div>
          <div className="min-w-[220px] flex-1 space-y-1">
            <Label>Token</Label>
            <Input
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder={provider === "gitlab" ? "glpat-…" : "ghp_…"}
            />
          </div>
          {option.needsBaseUrl ? (
            <div className="min-w-[200px] flex-1 space-y-1">
              <Label>Base URL</Label>
              <Input
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder="https://gitlab.com"
              />
            </div>
          ) : null}
          <div className="w-36 space-y-1">
            <Label>Label</Label>
            <Input value={label} onChange={(event) => setLabel(event.target.value)} placeholder="work" />
          </div>
          <Button onClick={() => void submit()} disabled={busy || !token.trim()}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Add key
          </Button>
        </div>
        <ErrorText>{error}</ErrorText>
      </div>
    </div>
  );
}

export interface LLMKeysProps {
  keys: LLMKey[];
  activeId: number | null;
  onActivate: (id: number) => Promise<void>;
  onCreate: (payload: LLMKeyCreate) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  onTest: (id: number) => Promise<KeyTestResult>;
}

export function LLMKeys({ keys, activeId, onActivate, onCreate, onDelete, onTest }: LLMKeysProps) {
  const [provider, setProvider] = useState("claude");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [defaultModel, setDefaultModel] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<Record<number, KeyTestResult>>({});
  const [testing, setTesting] = useState<number | null>(null);

  const option = LLM_OPTIONS.find((item) => item.value === provider) ?? LLM_OPTIONS[0];
  const ready = option.needsSecret ? apiKey.trim().length > 0 : true;

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await onCreate({
        provider: provider as LLMKeyCreate["provider"],
        api_key: option.needsSecret ? apiKey.trim() : null,
        base_url: baseUrl.trim() || null,
        default_model: defaultModel.trim() || null,
        label: label.trim() || null,
      });
      setApiKey("");
      setDefaultModel("");
      setLabel("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the key");
    } finally {
      setBusy(false);
    }
  }

  async function runTest(id: number) {
    setTesting(id);
    try {
      const result = await onTest(id);
      setResults((current) => ({ ...current, [id]: result }));
    } catch (err) {
      setResults((current) => ({
        ...current,
        [id]: { ok: false, detail: err instanceof Error ? err.message : "Test failed", metadata: null },
      }));
    } finally {
      setTesting(null);
    }
  }

  return (
    <div className="space-y-3">
      {keys.length === 0 ? (
        <p className="text-xs text-inkMuted">
          <KeyRound className="mr-1 inline h-3 w-3" /> No model provider configured yet.
        </p>
      ) : null}
      {keys.map((key) => (
        <KeyRow
          key={key.id}
          provider={key.provider}
          secret={key.api_key_masked}
          detail={
            [key.default_model, key.label, key.base_url].filter(Boolean).join(" · ") || null
          }
          active={key.id === activeId}
          result={results[key.id]}
          testing={testing === key.id}
          onActivate={() => void onActivate(key.id)}
          onTest={() => void runTest(key.id)}
          onDelete={() => void onDelete(key.id)}
        />
      ))}

      <div className="rounded-lg border border-dashed border-border p-3">
        <div className="flex flex-wrap items-end gap-2">
          <div className="w-40 space-y-1">
            <Label>Provider</Label>
            <Select value={provider} onChange={(event) => setProvider(event.target.value)}>
              {LLM_OPTIONS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </Select>
          </div>
          {option.needsSecret ? (
            <div className="min-w-[200px] flex-1 space-y-1">
              <Label>API key</Label>
              <Input
                type="password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder={provider === "claude" ? "sk-ant-…" : provider === "openai" ? "sk-…" : "API key"}
              />
            </div>
          ) : null}
          <div className="min-w-[190px] flex-1 space-y-1">
            <Label>{provider === "ollama_local" ? "Base URL" : "Base URL (optional)"}</Label>
            <Input
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder={
                provider === "ollama_local"
                  ? "http://localhost:11434"
                  : provider === "openai"
                    ? "https://api.openai.com/v1"
                    : provider === "ollama_cloud"
                      ? "https://ollama.com"
                      : "https://api.anthropic.com"
              }
            />
          </div>
          <div className="w-44 space-y-1">
            <Label>Default model</Label>
            <Input
              value={defaultModel}
              onChange={(event) => setDefaultModel(event.target.value)}
              placeholder={provider === "ollama_local" ? "llama3:8b" : "optional"}
            />
          </div>
          <Button onClick={() => void submit()} disabled={busy || !ready}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Add key
          </Button>
        </div>
        <ErrorText>{error}</ErrorText>
      </div>
    </div>
  );
}
