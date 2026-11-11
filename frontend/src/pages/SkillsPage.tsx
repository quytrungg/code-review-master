import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  Brain,
  CheckCircle2,
  FileText,
  FolderUp,
  Layers,
  Loader2,
  RefreshCw,
  Trash2,
  Upload,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Label, Select } from "@/components/ui/Input";
import { FoundationUpload } from "@/components/FoundationUpload";
import { SkillEvolutionModal } from "@/components/SkillEvolutionModal";
import { api, ApiError } from "@/services/api";
import type { ModelOption, SkillEvolutionAnalysis, SkillsResponse } from "@/types";

/** The stages the analysis moves through, shown while the model works. */
const EVOLUTION_STAGES = [
  "Gathering 30-day review interactions & user pushbacks…",
  "Correlating false positives against skill rules…",
  "Drafting proposed guideline updates…",
];

function formatChars(count: number): string {
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)} MB`;
  if (count >= 1000) return `${Math.round(count / 1000)}k chars`;
  return `${count} chars`;
}

export function SkillsPage() {
  const [data, setData] = useState<SkillsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);

  // Skill evolution: the foundation and the model to run the meta-analysis with.
  const [models, setModels] = useState<ModelOption[]>([]);
  const [model, setModel] = useState("");
  const [foundation, setFoundation] = useState("");
  const [analysing, setAnalysing] = useState(false);
  const [stage, setStage] = useState(0);
  const [analysis, setAnalysis] = useState<SkillEvolutionAnalysis | null>(null);
  const stageTimer = useRef<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [skills, catalog] = await Promise.all([api.listSkills(), api.listModels()]);
      setData(skills);
      setModels(catalog.models);
      setModel((current) => current || catalog.preferred || catalog.models[0]?.id || "");
      setFoundation((current) => current || skills.default);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load the skill library");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(
    () => () => {
      if (stageTimer.current !== null) window.clearInterval(stageTimer.current);
    },
    [],
  );

  /** Run the meta-analysis and open the workbench with its proposals. */
  async function evolve() {
    if (!foundation || !model) return;
    setAnalysing(true);
    setError(null);
    setNotice(null);
    setStage(0);
    // The stages are a readable trace of a single long call: the panel advances while the
    // model works, and the last stage stays up until the answer lands.
    if (stageTimer.current !== null) window.clearInterval(stageTimer.current);
    stageTimer.current = window.setInterval(() => {
      setStage((current) => Math.min(current + 1, EVOLUTION_STAGES.length - 1));
    }, 2500);
    try {
      const result = await api.analyzeSkillHistory(foundation, 30, model);
      setAnalysis(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The analysis failed.");
    } finally {
      if (stageTimer.current !== null) {
        window.clearInterval(stageTimer.current);
        stageTimer.current = null;
      }
      setAnalysing(false);
    }
  }

  async function uploadFile() {
    if (!file) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.uploadSkillFile(file);
      setNotice(`Saved ${result.path} (${result.bytes.toLocaleString()} bytes) to ${result.foundation}.`);
      setFile(null);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function createFoundation(name: string, files: File[], archive?: File) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const foundation = await api.createFoundation(name, files, archive);
      setNotice(
        `Created “${foundation.id}” with ${foundation.file_count} file(s) (${formatChars(foundation.total_chars)}).`,
      );
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the foundation");
      throw err;
    } finally {
      setBusy(false);
    }
  }

  async function removeFoundation(id: string) {
    if (!window.confirm(`Delete the foundation “${id}” and its files?`)) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.deleteFoundation(id);
      setNotice(`Deleted “${id}”.`);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not delete the foundation");
    } finally {
      setBusy(false);
    }
  }

  if (loading && !data) {
    return (
      <p className="flex items-center gap-2 text-sm text-inkMuted">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading skills…
      </p>
    );
  }

  const defaultFoundation = data?.foundations.find((item) => item.is_default);
  const uploaded = data?.foundations.filter((item) => !item.is_default) ?? [];
  const canWrite = data?.uploads_enabled !== false;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Skills</h1>
          <p className="text-sm text-inkMuted">
            The rule files injected into every prompt. A <strong>Core Skill Foundation</strong> is a
            folder of rules you can pick per review.
          </p>
        </div>
        <Button variant="secondary" onClick={() => void load()} disabled={loading || busy}>
          <RefreshCw className="h-4 w-4" /> Refresh
        </Button>
      </header>

      {error ? (
        <div className="flex items-start gap-2 rounded-xl border border-danger/40 bg-danger/10 px-4 py-3 text-xs text-danger">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
        </div>
      ) : null}
      {notice ? (
        <div className="flex items-start gap-2 rounded-xl border border-success/30 bg-success/10 px-4 py-3 text-xs text-success">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> {notice}
        </div>
      ) : null}

      <Card>
        <CardHeader
          icon={<Brain className="h-4 w-4" />}
          title="Evolve from review history"
          description="Let a model read your last 30 days of pushbacks and propose edits to the guideline files."
        />
        <CardBody>
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-[200px] flex-1 space-y-1">
              <Label htmlFor="evolve-foundation">Skill foundation</Label>
              <Select
                id="evolve-foundation"
                value={foundation}
                onChange={(event) => setFoundation(event.target.value)}
                disabled={analysing || busy}
              >
                {(data?.foundations ?? []).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.id}
                    {item.is_default ? " (default)" : ""} · {item.file_count} file(s)
                  </option>
                ))}
              </Select>
            </div>
            <div className="min-w-[200px] flex-1 space-y-1">
              <Label htmlFor="evolve-model">Model</Label>
              <Select
                id="evolve-model"
                value={model}
                onChange={(event) => setModel(event.target.value)}
                disabled={analysing || busy}
              >
                {model === "" ? (
                  <option value="">
                    {models.length === 0 ? "No providers configured" : "Select a model"}
                  </option>
                ) : null}
                {models.map((option) => (
                  <option key={option.id} value={option.id} disabled={!option.available}>
                    {option.label}
                    {option.available ? "" : ` (${option.note ?? "unavailable"})`}
                  </option>
                ))}
              </Select>
            </div>
            <Button onClick={() => void evolve()} disabled={analysing || busy || !foundation || !model}>
              {analysing ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Brain className="h-4 w-4" />
              )}
              {analysing ? "Analysing…" : "Evolve from review history"}
            </Button>
          </div>
          {models.length === 0 ? (
            <p className="text-xs text-inkMuted">
              Add a model key in Settings before running an analysis.
            </p>
          ) : null}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          icon={<BookOpen className="h-4 w-4" />}
          title="Default foundation"
          description="Every review uses this unless you pick another foundation."
          action={<Badge tone="accent">{defaultFoundation?.file_count ?? 0} file(s)</Badge>}
        />
        <CardBody>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="success">{data?.default ?? "code-review"}</Badge>
            <span className="text-xs text-inkMuted">
              {formatChars(defaultFoundation?.total_chars ?? 0)} of prompt material
            </span>
          </div>

          <details className="rounded-lg border border-border bg-canvas/40 px-3 py-2">
            <summary className="cursor-pointer text-xs text-inkMuted">
              {defaultFoundation?.file_count ?? 0} file(s) — show list
            </summary>
            <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto font-mono text-[11px] text-inkMuted">
              {defaultFoundation?.files.map((name) => (
                <li key={name} className="flex items-center gap-1.5">
                  <FileText className="h-3 w-3 shrink-0" /> {name}
                </li>
              ))}
            </ul>
          </details>

          {canWrite ? (
            <div className="space-y-2 rounded-lg border border-border bg-surfaceMuted/30 p-3">
              <p className="flex items-center gap-1.5 text-xs font-medium text-ink">
                <Upload className="h-3.5 w-3.5" /> Add a single skill file
              </p>
              <input
                type="file"
                accept=".md,.txt"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                className="block w-full cursor-pointer rounded-lg border border-border bg-canvas/70 p-2 text-xs text-inkMuted file:mr-3 file:rounded-md file:border-0 file:bg-surfaceMuted file:px-3 file:py-1.5 file:text-xs file:text-ink"
              />
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs text-inkMuted">
                  {file ? `${file.name} — ${Math.round(file.size / 1024)} KB` : "Markdown or plain text, up to 2 MB."}
                </p>
                <Button size="sm" onClick={() => void uploadFile()} disabled={!file || busy}>
                  {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
                  Upload file
                </Button>
              </div>
            </div>
          ) : (
            <p className="rounded-lg border border-dashed border-borderStrong/70 p-3 text-xs text-inkMuted">
              Skill files are read-only on this deployment. Add markdown to{" "}
              <code className="font-mono">code-review/</code> in the repository and redeploy.
            </p>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          icon={<Layers className="h-4 w-4" />}
          title="Core Skill Foundations"
          description="Folder-per-foundation rule sets; pick one when starting a review."
          action={<Badge>{uploaded.length}</Badge>}
        />
        <CardBody>
          {uploaded.length === 0 ? (
            <p className="rounded-lg border border-dashed border-borderStrong/70 p-4 text-center text-xs text-inkMuted">
              {canWrite
                ? "No uploaded foundations yet. Create one below from a folder or a .zip."
                : "No uploaded foundations. This deployment serves the bundled library only."}
            </p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {uploaded.map((foundation) => (
                <div key={foundation.id} className="rounded-xl border border-border bg-surfaceMuted/30 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-ink">{foundation.id}</p>
                      <p className="text-xs text-inkMuted">
                        {foundation.file_count} file(s) · {formatChars(foundation.total_chars)}
                      </p>
                    </div>
                    {canWrite ? (
                      <Button
                        variant="danger"
                        size="sm"
                        onClick={() => void removeFoundation(foundation.id)}
                        disabled={busy}
                        title="Delete this foundation"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    ) : null}
                  </div>
                  <ul className="mt-2 max-h-24 space-y-0.5 overflow-y-auto font-mono text-[11px] text-inkMuted">
                    {foundation.files.slice(0, 8).map((name) => (
                      <li key={name} className="truncate">
                        {name}
                      </li>
                    ))}
                    {foundation.files.length > 8 ? <li>… {foundation.files.length - 8} more</li> : null}
                  </ul>
                </div>
              ))}
            </div>
          )}

          {canWrite ? (
            <div className="rounded-xl border border-border bg-canvas/40 p-4">
              <p className="mb-3 flex items-center gap-1.5 text-sm font-medium text-ink">
                <FolderUp className="h-4 w-4" /> New foundation
              </p>
              <FoundationUpload onCreate={createFoundation} busy={busy} />
            </div>
          ) : null}
        </CardBody>
      </Card>

      {analysing ? (
        <div
          className="fixed inset-0 z-40 flex items-center justify-center bg-canvas/70 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-label="Analysing the review history"
        >
          <div className="w-full max-w-md space-y-3 rounded-xl border border-border bg-surface p-5 shadow-2xl">
            <p className="flex items-center gap-2 text-sm font-medium text-ink">
              <Loader2 className="h-4 w-4 animate-spin text-accent" /> Analysing the review history
            </p>
            <ol className="space-y-2">
              {EVOLUTION_STAGES.map((label, index) => (
                <li
                  key={label}
                  className={
                    index < stage
                      ? "flex items-center gap-2 text-xs text-success"
                      : index === stage
                        ? "flex items-center gap-2 text-xs text-ink"
                        : "flex items-center gap-2 text-xs text-inkMuted/60"
                  }
                >
                  {index < stage ? (
                    <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                  ) : index === stage ? (
                    <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-accent" />
                  ) : (
                    <span className="h-3.5 w-3.5 shrink-0 rounded-full border border-borderStrong/70" />
                  )}
                  {label}
                </li>
              ))}
            </ol>
            <p className="text-[11px] text-inkMuted">
              This sends the foundation&apos;s rules and the review history to your chosen model.
            </p>
          </div>
        </div>
      ) : null}

      {analysis ? (
        <SkillEvolutionModal
          foundation={
            data?.foundations.find((item) => item.id === foundation) ?? {
              id: foundation,
              label: foundation,
              is_default: false,
              file_count: 0,
              total_chars: 0,
              files: [],
            }
          }
          analysis={analysis}
          onClose={() => setAnalysis(null)}
          onApplied={(message) => {
            setAnalysis(null);
            setNotice(message);
            void load();
          }}
        />
      ) : null}
    </div>
  );
}
