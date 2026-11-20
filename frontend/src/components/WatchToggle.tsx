import { useState } from "react";
import { Bell, BellOff, BellRing, Loader2, RefreshCw, X } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { shortSha } from "@/lib/utils";
import { api, ApiError } from "@/services/api";
import type { CodeReviewDetail, ReviewWatch, WatchCheck } from "@/types";

type Pending = "toggle" | "stop" | "check";

/** What a check that started nothing means, in the reviewer's words. */
function noOpMessage(outcome: WatchCheck): string {
  if (outcome.status === "adopted") {
    return `Now tracking ${shortSha(outcome.head_sha)} — the next push starts a review.`;
  }
  if (outcome.status === "skipped") {
    return outcome.detail ?? "A check for this commit is already in flight.";
  }
  return `No new commits since ${shortSha(outcome.head_sha)}.`;
}

/**
 * Watch this pull request, or pause / stop watching it, and check it by hand.
 *
 * This component owns its own request and state: the toggle is one small mutation that must not
 * re-run the workspace's load, SSE subscription or thread selection, so it keeps its own `watch`
 * and reconciles with the page only when the workspace reloads.
 *
 * "Check now" runs the same claim a scheduled tick runs, for this pull request alone, so a reviewer
 * who just pushed does not wait for the next poll. `enabled` gates the poll, not the button: a
 * paused watch can still be checked.
 */
export function WatchToggle({ review }: { review: CodeReviewDetail }) {
  const navigate = useNavigate();
  const [watch, setWatch] = useState<ReviewWatch | null>(review.watch);
  const [pending, setPending] = useState<Pending | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const busy = pending !== null;

  const run = async (kind: Pending, action: () => Promise<void>) => {
    setPending(kind);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update the watch.");
    } finally {
      setPending(null);
    }
  };

  const start = () =>
    run("toggle", async () => {
      setWatch(await api.createWatch(review.id));
    });

  const toggle = () => {
    if (!watch) return;
    const next = !watch.enabled;
    return run("toggle", async () => {
      setWatch(await api.updateWatch(watch.id, next));
    });
  };

  const stop = () => {
    if (!watch) return;
    return run("stop", async () => {
      await api.deleteWatch(watch.id);
      setWatch(null);
    });
  };

  const check = () => {
    if (!watch) return;
    return run("check", async () => {
      setNotice(null);
      const outcome = await api.checkWatch(watch.id);
      if (outcome.status === "started" && outcome.review_id !== null) {
        navigate(`/reviews/${outcome.review_id}`);
        return;
      }
      setNotice(noOpMessage(outcome));
      // Re-read the row so "last check" (and a recorded failure) is what the server now has.
      const rows = await api.listWatches();
      setWatch(rows.find((row) => row.id === watch.id) ?? watch);
    });
  };

  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex items-center gap-1.5">
        {watch ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void toggle()}
            disabled={busy}
            title={
              watch.enabled
                ? "New commits on this pull request start a linked review. Click to pause the automatic check."
                : "Paused: new commits are not checked automatically. Click to resume."
            }
          >
            {pending === "toggle" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : watch.enabled ? (
              <BellRing className="h-3.5 w-3.5 text-success" />
            ) : (
              <BellOff className="h-3.5 w-3.5" />
            )}
            {watch.enabled ? "Watching" : "Paused"}
          </Button>
        ) : (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => void start()}
            disabled={busy}
            title="Check this pull request for new commits and review the delta automatically."
          >
            {pending === "toggle" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Bell className="h-3.5 w-3.5" />
            )}
            Watch for new commits
          </Button>
        )}
        {watch ? (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => void check()}
            disabled={busy}
            title="Check for new commits now instead of waiting for the next scheduled check."
          >
            {pending === "check" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            Check now
          </Button>
        ) : null}
        {watch ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void stop()}
            disabled={busy}
            title="Stop watching and delete this watch."
            aria-label="Stop watching this pull request"
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        ) : null}
      </div>

      {watch ? (
        <span className="text-[11px] text-inkMuted">
          {watch.enabled
            ? "Checks for new commits every 10 minutes"
            : "Paused — press Check now to review a push"}
          {watch.last_checked_at ? ` · last check ${watch.last_checked_at.slice(11, 16)}Z` : ""}
        </span>
      ) : null}
      {notice ? <span className="text-[11px] text-inkMuted">{notice}</span> : null}
      {watch?.last_error ? (
        <Badge tone="warning" className="max-w-md text-left">
          Last check failed: {watch.last_error}
        </Badge>
      ) : null}
      {error ? <span className="text-[11px] text-danger">{error}</span> : null}
    </div>
  );
}
