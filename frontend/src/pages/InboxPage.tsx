import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  CheckCircle2,
  ExternalLink,
  GitPullRequest,
  Inbox,
  Loader2,
  MessageSquare,
  RefreshCw,
  ShieldX,
  Sparkles,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody } from "@/components/ui/Card";
import { Select } from "@/components/ui/Input";
import { QuickReviewPanel } from "@/components/QuickReviewPanel";
import { StartReviewModal } from "@/components/StartReviewModal";
import { api, ApiError } from "@/services/api";
import { relativeTime } from "@/lib/utils";
import type { CachedPR, InboxStatus, QuickReviewEvent } from "@/types";

const STATUS_META: Record<InboxStatus, { label: string; tone: "warning" | "success" | "danger" | "accent" }> = {
  needs_review: { label: "Needs review", tone: "warning" },
  approved: { label: "Approved", tone: "success" },
  request_changed: { label: "Changes requested", tone: "danger" },
  commented: { label: "Commented", tone: "accent" },
};

export function InboxPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<CachedPR[]>([]);
  // Repo options come from the unfiltered cache: deriving them from `items` would shrink the
  // dropdown to whatever the active filters happen to leave visible.
  const [repos, setRepos] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<InboxStatus | "">("needs_review");
  const [repoFilter, setRepoFilter] = useState("");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [quickAction, setQuickAction] = useState<{ pr: CachedPR; event: QuickReviewEvent } | null>(null);
  const [startTarget, setStartTarget] = useState<CachedPR | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [filtered, all] = await Promise.all([
        api.listInbox({
          status: statusFilter || undefined,
          repo: repoFilter || undefined,
          unread: unreadOnly || undefined,
        }),
        api.listInbox(),
      ]);
      setItems(filtered);
      setRepos([...new Set(all.map((pr) => `${pr.repo_owner}/${pr.repo_name}`))].sort());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the inbox.");
    } finally {
      setLoading(false);
    }
  }, [statusFilter, repoFilter, unreadOnly]);

  useEffect(() => {
    void load();
  }, [load]);

  async function sync() {
    setSyncing(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.syncInbox();
      setItems(result.items);
      setRepos([...new Set(result.items.map((pr) => `${pr.repo_owner}/${pr.repo_name}`))].sort());
      const dropped = result.disappeared ? `, ${result.disappeared} closed` : "";
      setNotice(
        `Synced ${result.items.length} pull request${result.items.length === 1 ? "" : "s"}${dropped}.` +
          (result.warnings.length ? ` ${result.warnings.length} could not be refreshed.` : ""),
      );
      if (result.warnings.length) setError(result.warnings.join(" "));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sync failed.");
    } finally {
      setSyncing(false);
    }
  }

  function startReview(pr: CachedPR) {
    if (pr.linked_review_id) {
      navigate(`/reviews/${pr.linked_review_id}`);
      return;
    }
    setStartTarget(pr);
  }

  function applyUpdate(updated: CachedPR) {
    setItems((current) => current.map((row) => (row.id === updated.id ? updated : row)));
    setQuickAction(null);
    setNotice("Review posted to GitHub.");
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">PR Inbox</h1>
          <p className="text-sm text-inkMuted">
            Open pull requests waiting on you or your teams. Sync re-reads GitHub; the list is a
            local cache and costs no API calls between syncs.
          </p>
        </div>
        <Button variant="secondary" onClick={() => void sync()} disabled={syncing}>
          {syncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          Sync with GitHub
        </Button>
      </header>

      {notice ? (
        <p className="rounded-xl border border-success/40 bg-success/10 px-4 py-2.5 text-xs text-success">
          {notice}
        </p>
      ) : null}
      {error ? (
        <p className="rounded-xl border border-danger/40 bg-danger/10 px-4 py-2.5 text-xs text-danger">
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <Select
          aria-label="Filter by status"
          className="h-9 w-44 text-xs"
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value as InboxStatus | "")}
        >
          <option value="">Every status</option>
          {(Object.keys(STATUS_META) as InboxStatus[]).map((status) => (
            <option key={status} value={status}>
              {STATUS_META[status].label}
            </option>
          ))}
        </Select>
        <Select
          aria-label="Filter by repository"
          className="h-9 w-52 text-xs"
          value={repoFilter}
          onChange={(event) => setRepoFilter(event.target.value)}
        >
          <option value="">Every repository</option>
          {repos.map((repo) => (
            <option key={repo} value={repo}>
              {repo}
            </option>
          ))}
        </Select>
        <Button
          variant={unreadOnly ? "secondary" : "ghost"}
          size="sm"
          onClick={() => setUnreadOnly((current) => !current)}
        >
          Unread replies only
        </Button>
      </div>

      <Card>
        <CardBody>
          {loading ? (
            <p className="flex items-center gap-2 text-sm text-inkMuted">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading the inbox…
            </p>
          ) : items.length === 0 ? (
            <div className="rounded-xl border border-dashed border-borderStrong/70 p-8 text-center">
              <Inbox className="mx-auto h-6 w-6 text-inkMuted" />
              <p className="mt-2 text-sm text-ink">Nothing is waiting on you</p>
              <p className="mt-1 text-xs text-inkMuted">
                Sync reads your review requests and team queues from GitHub.
              </p>
              <Button className="mt-4" variant="secondary" size="sm" onClick={() => void sync()}>
                Sync with GitHub
              </Button>
            </div>
          ) : (
            <ul className="space-y-2">
              {items.map((pr) => {
                const meta = STATUS_META[pr.status];
                return (
                  <li
                    key={pr.id}
                    className="rounded-xl border border-border bg-surfaceMuted/30 px-4 py-3"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <GitPullRequest className="h-4 w-4 text-inkMuted" />
                          <span className="text-sm font-medium text-ink">{pr.title}</span>
                          <span className="text-xs text-inkMuted">#{pr.pr_number}</span>
                          {pr.involvement === "author" ? (
                            <Badge tone="neutral">Your PR</Badge>
                          ) : pr.involvement === "assignee" ? (
                            <Badge tone="neutral">Assigned to you</Badge>
                          ) : null}
                          <Badge tone={meta.tone}>{meta.label}</Badge>
                          {pr.has_unread_replies ? (
                            <Badge tone="accent">
                              {pr.unread_replies_count} unread{" "}
                              {pr.unread_replies_count === 1 ? "reply" : "replies"}
                            </Badge>
                          ) : null}
                        </div>
                        <p className="text-xs text-inkMuted">
                          {pr.repo_owner}/{pr.repo_name} · by {pr.author_username} · active{" "}
                          {relativeTime(pr.last_github_activity_at)}
                          {pr.linked_review_id ? (
                            <>
                              {" · "}
                              <Link
                                to={`/reviews/${pr.linked_review_id}`}
                                className="text-accent transition-colors hover:text-accentStrong"
                              >
                                review #{pr.linked_review_id}
                              </Link>
                            </>
                          ) : null}
                        </p>
                      </div>

                      <div className="flex flex-wrap items-center gap-1.5">
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => startReview(pr)}
                          title={
                            pr.linked_review_id
                              ? "Open the in-app AI review for this pull request"
                              : "Start an AI review of this pull request"
                          }
                        >
                          <Sparkles className="h-3.5 w-3.5" />
                          {pr.linked_review_id ? "Open review" : "AI review"}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setQuickAction({ pr, event: "APPROVE" })}
                        >
                          <CheckCircle2 className="h-3.5 w-3.5 text-success" /> Approve
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setQuickAction({ pr, event: "REQUEST_CHANGES" })}
                        >
                          <ShieldX className="h-3.5 w-3.5 text-danger" /> Request changes
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setQuickAction({ pr, event: "COMMENT" })}
                        >
                          <MessageSquare className="h-3.5 w-3.5 text-accent" /> Comment
                        </Button>
                        <a
                          href={pr.pr_url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-transparent px-2.5 text-xs text-inkMuted transition-colors hover:bg-surfaceMuted/60 hover:text-ink"
                        >
                          <ExternalLink className="h-3.5 w-3.5" /> GitHub
                        </a>
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </CardBody>
      </Card>

      {quickAction ? (
        <QuickReviewPanel
          pr={quickAction.pr}
          event={quickAction.event}
          onClose={() => setQuickAction(null)}
          onDone={applyUpdate}
        />
      ) : null}

      {startTarget ? (
        <StartReviewModal
          pr={startTarget}
          onClose={() => setStartTarget(null)}
          onStarted={(reviewId) => {
            setStartTarget(null);
            navigate(`/reviews/${reviewId}`);
          }}
        />
      ) : null}
    </div>
  );
}
