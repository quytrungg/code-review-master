import { Bell, BellOff, GitBranch, Loader2, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { relativeTime, shortSha } from "@/lib/utils";
import type { ReviewWatch } from "@/types";

/**
 * The watches this account holds. Presentational: the dashboard owns the fetch and the mutations,
 * so a refresh (or a failed request) is reported in one place.
 */
export function WatchesPanel({
  watches,
  busyId,
  onToggle,
  onDelete,
}: {
  watches: ReviewWatch[];
  busyId: number | null;
  onToggle: (watch: ReviewWatch, enabled: boolean) => void;
  onDelete: (watch: ReviewWatch) => void;
}) {
  const active = watches.filter((watch) => watch.enabled).length;

  return (
    <Card>
      <CardHeader
        icon={<Bell className="h-4 w-4" />}
        title="Watched pull requests"
        description={
          watches.length === 0
            ? "Nothing is watched yet. Open a review and press “Watch for new commits” to review each new push automatically."
            : `${active} of ${watches.length} watching for new commits. A push starts a linked review of just the delta.`
        }
      />
      {watches.length > 0 ? (
        <CardBody className="space-y-2">
          {watches.map((watch) => {
            const busy = busyId === watch.id;
            return (
              <div
                key={watch.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-surfaceMuted/30 px-3 py-2"
              >
                <div className="min-w-0 space-y-0.5">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="inline-flex items-center gap-1 font-mono text-xs text-inkMuted">
                      <GitBranch className="h-3.5 w-3.5" />
                      {watch.repo_full_name ?? "unknown repo"}
                      {watch.pr_number ? `#${watch.pr_number}` : ""}
                    </span>
                    {watch.enabled ? (
                      <Badge tone="success">Watching</Badge>
                    ) : (
                      <Badge tone="neutral">Paused</Badge>
                    )}
                    {watch.last_error ? <Badge tone="warning">Last check failed</Badge> : null}
                  </div>
                  <p className="text-[11px] text-inkMuted">
                    head {watch.last_seen_commit_id ? shortSha(watch.last_seen_commit_id) : "—"} · last
                    check {relativeTime(watch.last_checked_at)}
                    {watch.last_review_id ? (
                      <>
                        {" · "}
                        <Link
                          to={`/reviews/${watch.last_review_id}`}
                          className="text-accent transition-colors hover:text-accentStrong"
                        >
                          review #{watch.last_review_id}
                        </Link>
                      </>
                    ) : null}
                  </p>
                  {watch.last_error ? (
                    <p className="text-[11px] text-warning">{watch.last_error}</p>
                  ) : null}
                </div>

                <div className="flex items-center gap-1.5">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => onToggle(watch, !watch.enabled)}
                    title={watch.enabled ? "Pause this watch" : "Resume this watch"}
                  >
                    {busy ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : watch.enabled ? (
                      <BellOff className="h-3.5 w-3.5" />
                    ) : (
                      <Bell className="h-3.5 w-3.5" />
                    )}
                    {watch.enabled ? "Pause" : "Resume"}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => onDelete(watch)}
                    title="Stop watching and delete this watch"
                    aria-label={`Delete the watch on ${watch.repo_full_name ?? "this pull request"}`}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            );
          })}
        </CardBody>
      ) : null}
    </Card>
  );
}
