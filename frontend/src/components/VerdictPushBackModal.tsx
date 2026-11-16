import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, MessageSquareWarning, X, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Label, Textarea } from "@/components/ui/Input";
import { api, ApiError } from "@/services/api";
import type { CodeReviewDetail, ReviewVerdict, VerdictPushback } from "@/types";

const VERDICT_LABEL: Record<ReviewVerdict, string> = {
  APPROVE: "Approve",
  REQUEST_CHANGES: "Request changes",
  COMMENT: "Comment",
};

/**
 * Argue with the AI's suggested verdict. The reviewer writes why they disagree; the model re-reads
 * the review state and answers whether that changes its mind. It never publishes anything — an
 * agreeing answer only rewrites the advisory opinion, which the reviewer still applies themselves.
 */
export function VerdictPushBackModal({
  review,
  event,
  onClose,
}: {
  review: CodeReviewDetail;
  /** The event currently selected in the action bar, so "Use …" only appears when it would change it. */
  event: ReviewVerdict;
  /** Called once, with the refreshed review and the verdict the reviewer chose to adopt. */
  onClose: (result: { review: CodeReviewDetail; useVerdict?: ReviewVerdict } | null) => void;
}) {
  const [argument, setArgument] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answer, setAnswer] = useState<VerdictPushback | null>(null);
  const [refreshed, setRefreshed] = useState<CodeReviewDetail | null>(null);
  const [history, setHistory] = useState<VerdictPushback[]>([]);

  const opinion = refreshed ?? review;
  const ready = argument.trim().length > 0 && !busy;
  // "Request changes → Comment", but just "Comment" when the verdict held and only the confidence moved.
  const transition =
    answer && answer.previous_verdict && answer.previous_verdict !== answer.verdict
      ? `${VERDICT_LABEL[answer.previous_verdict]} → ${VERDICT_LABEL[answer.verdict]}`
      : answer
        ? VERDICT_LABEL[answer.verdict]
        : "";

  useEffect(() => {
    let cancelled = false;
    api
      .listVerdictPushbacks(review.id)
      .then((rows) => {
        if (!cancelled) setHistory(rows);
      })
      .catch(() => {
        // History is context, not the job: a failure here must not block the push-back itself.
        if (!cancelled) setHistory([]);
      });
    return () => {
      cancelled = true;
    };
  }, [review.id]);

  function close() {
    const result = refreshed ? { review: refreshed } : null;
    onClose(result);
  }

  async function submit() {
    setBusy(true);
    setError(null);
    setAnswer(null);
    try {
      const response = await api.pushBackVerdict(review.id, argument.trim());
      setAnswer(response.pushback);
      setRefreshed(response.review);
      setHistory((current) => [response.pushback, ...current]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The model could not answer. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <button
        type="button"
        aria-label="Close push-back"
        className="absolute inset-0 bg-canvas/60 backdrop-blur-sm"
        onClick={close}
      />
      <div className="relative flex max-h-[85vh] w-full max-w-2xl flex-col gap-4 rounded-xl border border-border bg-surface p-5 shadow-2xl">
        <header className="flex items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <h2 className="text-sm font-semibold text-ink">Push back on the AI opinion</h2>
            <p className="text-xs text-inkMuted">
              Say why you disagree. The model re-reads this review and decides whether that changes
              its verdict — nothing is published here.
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={close} aria-label="Close" disabled={busy}>
            <X className="h-4 w-4" />
          </Button>
        </header>

        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surfaceMuted/30 px-3 py-2">
          <span className="label-text">Its opinion</span>
          <Badge tone="accent">
            {opinion.suggested_verdict ? VERDICT_LABEL[opinion.suggested_verdict] : "No opinion"}
            {opinion.confidence_percentage !== null ? ` · ${opinion.confidence_percentage}%` : ""}
          </Badge>
          {opinion.suggested_verdict_note ? (
            <span className="min-w-0 flex-1 truncate text-[11px] text-inkMuted" title={opinion.suggested_verdict_note}>
              {opinion.suggested_verdict_note}
            </span>
          ) : null}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="pushback-argument">Your reasoning</Label>
          <Textarea
            id="pushback-argument"
            rows={5}
            maxLength={2000}
            value={argument}
            onChange={(event) => setArgument(event.target.value)}
            disabled={busy}
            placeholder="e.g. The migration only adds a nullable column and the worker is behind a flag that is off in production, so this does not block the deploy."
          />
          <p className="text-[11px] text-inkMuted">
            {argument.trim().length}/2000 · concrete reasons land better than “this is wrong”.
          </p>
        </div>

        {error ? (
          <p className="flex items-start gap-1.5 rounded-lg border border-danger/40 bg-danger/10 px-3 py-1.5 text-xs text-danger">
            <MessageSquareWarning className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {error}
          </p>
        ) : null}

        {answer ? (
          <div
            className={
              answer.agrees
                ? "space-y-2 rounded-lg border border-success/40 bg-success/10 px-3 py-2.5"
                : "space-y-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2.5"
            }
          >
            <div className="flex flex-wrap items-center gap-2 text-xs">
              {answer.agrees ? (
                <span className="flex items-center gap-1 font-medium text-success">
                  <CheckCircle2 className="h-3.5 w-3.5" /> It agrees
                </span>
              ) : (
                <span className="flex items-center gap-1 font-medium text-warning">
                  <XCircle className="h-3.5 w-3.5" /> It still disagrees
                </span>
              )}
              <span className="flex items-center text-inkMuted">
                {transition}
                {answer.confidence !== null ? ` · ${answer.confidence}%` : ""}
                {answer.previous_confidence !== null && answer.previous_confidence !== answer.confidence ? (
                  <span className="ml-1 opacity-70">(was {answer.previous_confidence}%)</span>
                ) : null}
              </span>
            </div>
            <p className="text-sm text-ink">{answer.response}</p>
          </div>
        ) : null}

        {history.length > 0 ? (
          <details className="rounded-lg border border-border bg-surfaceMuted/20 px-3 py-2">
            <summary className="cursor-pointer text-xs text-inkMuted">
              Earlier push-backs ({history.length})
            </summary>
            <ul className="mt-2 space-y-2">
              {history.map((entry) => (
                <li key={entry.id} className="border-t border-border pt-2 text-[11px] text-inkMuted first:border-0 first:pt-0">
                  <p className="text-ink">{entry.argument}</p>
                  <p className="mt-0.5">
                    {entry.agrees ? "Agreed" : "Held"} · {VERDICT_LABEL[entry.verdict]}
                    {entry.confidence !== null ? ` · ${entry.confidence}%` : ""} — {entry.response}
                  </p>
                </li>
              ))}
            </ul>
          </details>
        ) : null}

        <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-3">
          <Button variant="ghost" onClick={close} disabled={busy}>
            Close
          </Button>
          <Button onClick={() => void submit()} disabled={!ready}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <MessageSquareWarning className="h-4 w-4" />}
            {busy ? "Asking the model…" : "Push back"}
          </Button>
          {answer?.agrees && answer.verdict !== event ? (
            <Button
              variant="secondary"
              onClick={() => onClose({ review: refreshed ?? review, useVerdict: answer.verdict })}
            >
              Use {VERDICT_LABEL[answer.verdict]}
            </Button>
          ) : null}
        </footer>
      </div>
    </div>
  );
}
