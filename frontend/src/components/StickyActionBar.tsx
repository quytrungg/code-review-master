import { CheckCircle2, Loader2, Send, ShieldCheck, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import type { ReviewVerdict } from "@/types";

const VERDICTS: { value: ReviewVerdict; label: string; tone: string }[] = [
  { value: "REQUEST_CHANGES", label: "Request changes", tone: "text-danger border-danger/50 bg-danger/10" },
  { value: "APPROVE", label: "Approve", tone: "text-success border-success/50 bg-success/10" },
  { value: "COMMENT", label: "Comment", tone: "text-accent border-accent/50 bg-accent/10" },
];

const VERDICT_LABEL: Record<ReviewVerdict, string> = {
  APPROVE: "Approve",
  REQUEST_CHANGES: "Request changes",
  COMMENT: "Comment",
};

export interface StickyActionBarProps {
  pendingCount: number;
  verdict: ReviewVerdict;
  onVerdict: (verdict: ReviewVerdict) => void;
  aiVerdict?: ReviewVerdict | null;
  aiConfidence?: number | null;
  aiNote?: string | null;
  onUseAiVerdict?: () => void;
  onSubmit: () => void;
  onApply: () => void;
  submitting?: boolean;
  applying?: boolean;
  applyLabel?: string;
  applyCount?: number;
  submitDisabledReason?: string | null;
  applyDisabledReason?: string | null;
  error?: string | null;
  notice?: string | null;
}

export function StickyActionBar({
  pendingCount,
  verdict,
  onVerdict,
  aiVerdict = null,
  aiConfidence = null,
  aiNote = null,
  onUseAiVerdict,
  onSubmit,
  onApply,
  submitting = false,
  applying = false,
  applyLabel = "Apply to GitHub",
  applyCount = 0,
  submitDisabledReason = null,
  applyDisabledReason = null,
  error = null,
  notice = null,
}: StickyActionBarProps) {
  return (
    <div className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-canvas/95 px-5 py-3 backdrop-blur-xl">
      <div className="mx-auto flex max-w-7xl flex-col gap-3">
        {error ? (
          <p className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-1.5 text-xs text-danger">
            {error}
          </p>
        ) : notice ? (
          <p className="flex items-center gap-1.5 rounded-lg border border-success/30 bg-success/10 px-3 py-1.5 text-xs text-success">
            <CheckCircle2 className="h-3.5 w-3.5" /> {notice}
          </p>
        ) : null}

        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1.5">
            <span className="label-text">Review event</span>
            <div className="flex items-center gap-1.5">
              {VERDICTS.map(({ value, label, tone }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => onVerdict(value)}
                  className={cn(
                    "h-9 rounded-lg border px-3 text-xs font-medium transition-colors",
                    verdict === value
                      ? tone
                      : "border-border bg-surfaceMuted/50 text-inkMuted hover:text-ink",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="min-w-[240px] space-y-1.5 border-l border-border pl-3">
            <span className="label-text flex items-center gap-1">
              <Sparkles className="h-3 w-3" /> AI opinion
            </span>
            {aiVerdict ? (
              <div className="flex items-center gap-2">
                <span className="rounded-md border border-accent/40 bg-accent/10 px-2 py-1 text-xs font-medium text-accent">
                  {VERDICT_LABEL[aiVerdict]}
                  {aiConfidence !== null ? ` · ${aiConfidence}%` : ""}
                </span>
                <div className="h-1.5 w-20 overflow-hidden rounded-full bg-surfaceMuted">
                  <div
                    className={cn(
                      "h-full",
                      (aiConfidence ?? 0) >= 70
                        ? "bg-success"
                        : (aiConfidence ?? 0) >= 40
                          ? "bg-warning"
                          : "bg-danger",
                    )}
                    style={{ width: `${Math.max(4, aiConfidence ?? 0)}%` }}
                  />
                </div>
                {onUseAiVerdict ? (
                  <button
                    type="button"
                    onClick={onUseAiVerdict}
                    disabled={verdict === aiVerdict}
                    className="text-[11px] text-inkMuted underline decoration-borderStrong underline-offset-2 hover:text-ink disabled:opacity-40"
                  >
                    {verdict === aiVerdict ? "adopted" : "use it"}
                  </button>
                ) : null}
              </div>
            ) : (
              <p className="text-[11px] text-inkMuted">No opinion recorded for this review.</p>
            )}
            {aiNote ? (
              <p className="max-w-[320px] truncate text-[11px] text-inkMuted" title={aiNote}>
                {aiNote}
              </p>
            ) : null}
          </div>

          <div className="flex flex-1 items-center justify-end gap-2">
            <Button
              variant="secondary"
              onClick={onSubmit}
              disabled={submitting || pendingCount === 0}
              title={submitDisabledReason ?? undefined}
            >
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
              Submit responses{pendingCount > 0 ? ` (${pendingCount})` : ""}
            </Button>
            <Button
              onClick={onApply}
              disabled={applying || applyCount === 0 || Boolean(applyDisabledReason)}
              title={applyDisabledReason ?? undefined}
            >
              {applying ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <ShieldCheck className="h-4 w-4" />
              )}
              {applying ? "Publishing…" : applyLabel}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

