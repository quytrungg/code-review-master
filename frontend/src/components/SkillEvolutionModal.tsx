import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  Columns2,
  Copy,
  FilePlus2,
  FileText,
  GitPullRequest,
  Loader2,
  Rows3,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input, Label, Textarea } from "@/components/ui/Input";
import { MarkdownDiff, type DiffViewMode } from "@/components/MarkdownDiff";
import { cn } from "@/lib/utils";
import { api, ApiError } from "@/services/api";
import type {
  Foundation,
  SkillEvolutionAction,
  SkillEvolutionAnalysis,
  SkillEvolutionFileChange,
  SkillFileModification,
} from "@/types";

const ACTION_LABEL: Record<SkillEvolutionAction, string> = {
  modify: "Modified",
  create: "Created",
  delete: "Removed",
};

const ACTION_TONE: Record<SkillEvolutionAction, "accent" | "success" | "danger"> = {
  modify: "accent",
  create: "success",
  delete: "danger",
};

/** The content that will be written for one proposal, whatever the action is. */
function contentOf(proposal: SkillFileModification): string {
  return proposal.action === "delete" ? "" : proposal.proposed_content;
}

function FileNavigationItem({
  proposal,
  selected,
  accepted,
  onSelect,
  onToggle,
}: {
  proposal: SkillFileModification;
  selected: boolean;
  accepted: boolean;
  onSelect: () => void;
  onToggle: () => void;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border p-2 transition-colors",
        selected ? "border-accent/50 bg-accent/5" : "border-border bg-surfaceMuted/30",
      )}
    >
      <div className="flex items-start gap-2">
        <button
          type="button"
          onClick={onToggle}
          disabled={proposal.action === "delete"}
          title={
            proposal.action === "delete"
              ? "A removed file cannot be kept — accept it to delete the file"
              : accepted
                ? "Do not apply this file"
                : "Apply this file"
          }
          aria-pressed={accepted}
          className={cn(
            "mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded border transition-colors",
            accepted
              ? "border-accent/60 bg-accent/20 text-accent"
              : "border-borderStrong/70 text-transparent",
            proposal.action === "delete" ? "opacity-40" : "",
          )}
        >
          <Check className="h-3 w-3" />
        </button>
        <button type="button" onClick={onSelect} className="min-w-0 flex-1 text-left">
          <span className="flex items-center gap-1.5">
            {proposal.action === "create" ? (
              <FilePlus2 className="h-3 w-3 shrink-0 text-success" />
            ) : proposal.action === "delete" ? (
              <Trash2 className="h-3 w-3 shrink-0 text-danger" />
            ) : (
              <FileText className="h-3 w-3 shrink-0 text-inkMuted" />
            )}
            <span className="truncate font-mono text-[11px] text-ink">{proposal.file_path}</span>
          </span>
          <span className="mt-1 flex flex-wrap items-center gap-1">
            <Badge tone={ACTION_TONE[proposal.action]}>{ACTION_LABEL[proposal.action]}</Badge>
            {proposal.evidence_review_ids.length > 0 ? (
              <span className="text-[10px] text-inkMuted">
                triggered by {proposal.evidence_review_ids.length} pushback
                {proposal.evidence_review_ids.length === 1 ? "" : "s"}
              </span>
            ) : null}
          </span>
        </button>
      </div>
    </div>
  );
}

/**
 * The Skill Evolution Workbench.
 *
 * Shows what the meta-analysis proposed for one skill foundation: every proposed file with its
 * rationale and evidence, a diff the operator can read, a per-file accept switch, and the two
 * ways to land the change — in place, or in a brand-new foundation.
 */
export function SkillEvolutionModal({
  foundation,
  analysis,
  onClose,
  onApplied,
}: {
  foundation: Foundation;
  analysis: SkillEvolutionAnalysis;
  onClose: () => void;
  onApplied: (message: string) => void;
}) {
  const [selectedPath, setSelectedPath] = useState(analysis.file_modifications[0]?.file_path ?? "");
  const [accepted, setAccepted] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(analysis.file_modifications.map((item) => [item.file_path, true])),
  );
  const [edited, setEdited] = useState<Record<string, string>>({});
  const [mode, setMode] = useState<DiffViewMode>("unified");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cloneOpen, setCloneOpen] = useState(false);
  const [cloneName, setCloneName] = useState("");
  const [confirming, setConfirming] = useState(false);

  const selected = useMemo(
    () => analysis.file_modifications.find((item) => item.file_path === selectedPath) ?? null,
    [analysis.file_modifications, selectedPath],
  );

  const acceptedPaths = analysis.file_modifications
    .filter((item) => accepted[item.file_path])
    .map((item) => item.file_path);

  const changes: SkillEvolutionFileChange[] = analysis.file_modifications
    .filter((item) => accepted[item.file_path])
    .map((item) => ({
      file_path: item.file_path,
      action: item.action,
      content: edited[item.file_path] ?? contentOf(item),
    }));

  async function apply() {
    setBusy(true);
    setError(null);
    try {
      const result = await api.applySkillEvolution(foundation.id, changes);
      onApplied(
        `Updated ${result.applied.length} file(s) in ${foundation.id}. The previous version is in ${result.backup_path}.`,
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not apply the changes.");
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  }

  async function cloneAndApply() {
    const name = cloneName.trim();
    if (!name) {
      setError("Enter a name for the new foundation.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await api.cloneSkillEvolution(foundation.id, name, changes);
      onApplied(
        `Created “${result.foundation.id}” with ${result.applied.length} changed file(s). The original ${foundation.id} is untouched.`,
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the new foundation.");
    } finally {
      setBusy(false);
    }
  }

  const nothingSelected = changes.length === 0;

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Skill evolution workbench"
    >
      <button
        type="button"
        aria-label="Close the workbench"
        className="absolute inset-0 bg-canvas/70 backdrop-blur-sm"
        onClick={onClose}
        disabled={busy}
      />
      <div className="relative flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-xl border border-border bg-surface shadow-2xl">
        <header className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0 space-y-1">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-ink">
              <Sparkles className="h-4 w-4 text-accent" /> Skill evolution workbench
            </h2>
            <p className="text-xs text-inkMuted">
              {foundation.id} · {analysis.history.reviews} review(s),{" "}
              {analysis.history.interactions} pushback(s) in the last {analysis.history.days} days
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close" disabled={busy}>
            <X className="h-4 w-4" />
          </Button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {analysis.file_modifications.length === 0 ? (
            <div className="rounded-xl border border-border bg-surfaceMuted/30 p-6 text-center">
              <Check className="mx-auto h-6 w-6 text-success" />
              <p className="mt-2 text-sm font-medium text-ink">
                No guideline adjustments needed
              </p>
              <p className="mx-auto mt-1 max-w-md text-xs text-inkMuted">
                {analysis.analysis_summary ||
                  "Your skill foundation closely matches your team's review patterns."}
              </p>
            </div>
          ) : (
            <>
              <section className="rounded-xl border border-border bg-surfaceMuted/30 p-4">
                <p className="flex items-center gap-1.5 text-xs font-medium text-ink">
                  <GitPullRequest className="h-3.5 w-3.5 text-accent" /> What the model found
                </p>
                <p className="mt-1.5 whitespace-pre-wrap text-xs leading-relaxed text-inkMuted">
                  {analysis.analysis_summary}
                </p>
                {analysis.warnings.length > 0 ? (
                  <ul className="mt-2 space-y-1">
                    {analysis.warnings.map((warning) => (
                      <li key={warning} className="flex items-start gap-1.5 text-[11px] text-warning">
                        <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" /> {warning}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </section>

              <div className="mt-4 grid gap-4 lg:grid-cols-[260px_1fr]">
                <aside className="space-y-2">
                  <p className="text-[11px] uppercase tracking-wide text-inkMuted">
                    Proposed files ({acceptedPaths.length}/{analysis.file_modifications.length}{" "}
                    selected)
                  </p>
                  {analysis.file_modifications.map((proposal) => (
                    <FileNavigationItem
                      key={proposal.file_path}
                      proposal={proposal}
                      selected={proposal.file_path === selectedPath}
                      accepted={Boolean(accepted[proposal.file_path])}
                      onSelect={() => setSelectedPath(proposal.file_path)}
                      onToggle={() =>
                        setAccepted((current) => ({
                          ...current,
                          [proposal.file_path]: !current[proposal.file_path],
                        }))
                      }
                    />
                  ))}
                </aside>

                <section className="min-w-0 space-y-3">
                  {selected ? (
                    <>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="min-w-0">
                          <p className="truncate font-mono text-xs text-ink">{selected.file_path}</p>
                          {selected.rationale ? (
                            <p className="mt-1 text-[11px] text-inkMuted">{selected.rationale}</p>
                          ) : null}
                        </div>
                        <div className="flex items-center gap-1.5">
                          <div className="flex overflow-hidden rounded-lg border border-border">
                            <button
                              type="button"
                              onClick={() => setMode("unified")}
                              className={cn(
                                "flex items-center gap-1 px-2 py-1 text-[11px] transition-colors",
                                mode === "unified"
                                  ? "bg-accent/15 text-accent"
                                  : "text-inkMuted hover:text-ink",
                              )}
                            >
                              <Rows3 className="h-3 w-3" /> Unified
                            </button>
                            <button
                              type="button"
                              onClick={() => setMode("split")}
                              className={cn(
                                "flex items-center gap-1 px-2 py-1 text-[11px] transition-colors",
                                mode === "split"
                                  ? "bg-accent/15 text-accent"
                                  : "text-inkMuted hover:text-ink",
                              )}
                            >
                              <Columns2 className="h-3 w-3" /> Split
                            </button>
                          </div>
                          {selected.action !== "delete" ? (
                            <Button
                              variant="secondary"
                              size="sm"
                              onClick={() => setEditing((current) => !current)}
                            >
                              {editing ? "Show diff" : "Edit text"}
                            </Button>
                          ) : null}
                        </div>
                      </div>

                      {editing && selected.action !== "delete" ? (
                        <Textarea
                          rows={16}
                          value={edited[selected.file_path] ?? selected.proposed_content}
                          onChange={(event) =>
                            setEdited((current) => ({
                              ...current,
                              [selected.file_path]: event.target.value,
                            }))
                          }
                          className="font-mono text-[12px] leading-relaxed"
                        />
                      ) : (
                        <MarkdownDiff diff={selected.unified_diff} mode={mode} />
                      )}

                      {selected.evidence_review_ids.length > 0 ? (
                        <p className="text-[11px] text-inkMuted">
                          Triggered by {selected.evidence_review_ids.length} pushback
                          {selected.evidence_review_ids.length === 1 ? "" : "s"} across PR #
                          {selected.evidence_review_ids.join(", #")}.
                        </p>
                      ) : null}
                    </>
                  ) : (
                    <p className="text-xs text-inkMuted">Pick a file to see its proposed change.</p>
                  )}
                </section>
              </div>
            </>
          )}

          {cloneOpen ? (
            <section className="mt-4 rounded-xl border border-accent/40 bg-accent/5 p-4">
              <p className="flex items-center gap-1.5 text-xs font-medium text-ink">
                <Copy className="h-3.5 w-3.5 text-accent" /> Clone and apply
              </p>
              <p className="mt-1 text-[11px] text-inkMuted">
                A copy of {foundation.id} is created with these changes; the original is left
                untouched. Lowercase words separated by “-”.
              </p>
              <div className="mt-3 flex flex-wrap items-end gap-2">
                <div className="min-w-[220px] flex-1 space-y-1">
                  <Label htmlFor="clone-foundation-name">New foundation name</Label>
                  <Input
                    id="clone-foundation-name"
                    value={cloneName}
                    onChange={(event) => setCloneName(event.target.value)}
                    placeholder="team-standards-v2"
                    disabled={busy}
                  />
                </div>
                <Button onClick={() => void cloneAndApply()} disabled={busy || nothingSelected}>
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Copy className="h-4 w-4" />}
                  Create and apply
                </Button>
                <Button variant="ghost" onClick={() => setCloneOpen(false)} disabled={busy}>
                  Cancel
                </Button>
              </div>
            </section>
          ) : null}

          {error ? (
            <p className="mt-3 flex items-start gap-1.5 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {error}
            </p>
          ) : null}
        </div>

        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-3">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <div className="flex flex-wrap items-center gap-2">
            {confirming ? (
              <>
                <span className="text-xs text-inkMuted">
                  This will update {changes.length} file(s) in {foundation.id}.
                </span>
                <Button variant="secondary" onClick={() => setConfirming(false)} disabled={busy}>
                  Cancel
                </Button>
                <Button onClick={() => void apply()} disabled={busy}>
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  Confirm apply
                </Button>
              </>
            ) : (
              <>
                <Button
                  variant="secondary"
                  onClick={() => setCloneOpen(true)}
                  disabled={busy || nothingSelected}
                >
                  <Copy className="h-4 w-4" /> Clone and apply
                </Button>
                <Button
                  onClick={() => setConfirming(true)}
                  disabled={busy || nothingSelected || analysis.file_modifications.length === 0}
                >
                  Apply changes
                </Button>
              </>
            )}
          </div>
        </footer>
      </div>
    </div>
  );
}
