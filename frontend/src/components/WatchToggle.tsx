import { useState } from "react";
import { Bell, BellOff, BellRing, Loader2, X } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { api, ApiError } from "@/services/api";
import type { CodeReviewDetail, ReviewWatch } from "@/types";

/**
 * Watch this pull request, or pause / stop watching it.
 *
 * This component owns its own request and state: the toggle is one small mutation that must not
 * re-run the workspace's load, SSE subscription or thread selection, so it keeps its own `watch`
 * and reconciles with the page only when the workspace reloads.
 */
export function WatchToggle({ review }: { review: CodeReviewDetail }) {
  const [watch, setWatch] = useState<ReviewWatch | null>(review.watch);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update the watch.");
    } finally {
      setBusy(false);
    }
  };

  const start = () =>
    run(async () => {
      setWatch(await api.createWatch(review.id));
    });

  const toggle = () => {
    if (!watch) return;
    const next = !watch.enabled;
    return run(async () => {
      setWatch(await api.updateWatch(watch.id, next));
    });
  };

  const stop = () => {
    if (!watch) return;
    return run(async () => {
      await api.deleteWatch(watch.id);
      setWatch(null);
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
                ? "New commits on this pull request start a linked review. Click to pause."
                : "Paused: new commits are not reviewed. Click to resume."
            }
          >
            {busy ? (
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
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Bell className="h-3.5 w-3.5" />}
            Watch for new commits
          </Button>
        )}
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

      {watch?.enabled ? (
        <span className="text-[11px] text-inkMuted">
          Checks for new commits every 10 minutes
          {watch.last_checked_at ? ` · last check ${watch.last_checked_at.slice(11, 16)}Z` : ""}
        </span>
      ) : null}
      {watch?.last_error ? (
        <Badge tone="warning" className="max-w-md text-left">
          Last check failed: {watch.last_error}
        </Badge>
      ) : null}
      {error ? <span className="text-[11px] text-danger">{error}</span> : null}
    </div>
  );
}
