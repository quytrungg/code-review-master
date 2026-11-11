import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, GitPullRequest, Loader2, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { NewReviewPanel } from "@/components/NewReviewPanel";
import { WatchesPanel } from "@/components/WatchesPanel";
import { api, ApiError } from "@/services/api";
import {
  compactNumber,
  estimatedCost,
  formatDuration,
  formatPercent,
  formatUsd,
  relativeTime,
} from "@/lib/utils";
import type { AnalyticsResponse, BudgetStatus, CodeReviewSummary, ReviewWatch } from "@/types";

/** The one line the caps breach, in the order a reader cares about it. */
function budgetWarnings(budget: BudgetStatus): string[] {
  const warnings: string[] = [];
  if (budget.token_pct !== null && budget.token_pct >= 80) {
    warnings.push(
      `${formatPercent(budget.token_pct)} of the monthly token budget (${compactNumber(
        budget.tokens_used,
      )} of ${compactNumber(budget.token_budget)})`,
    );
  }
  if (budget.dollar_pct !== null && budget.dollar_pct >= 80) {
    warnings.push(
      `${formatPercent(budget.dollar_pct)} of the monthly spend cap (${estimatedCost(
        budget.dollars_used,
      )} of ${formatUsd(budget.dollar_budget)})`,
    );
  }
  return warnings;
}

function BudgetAlert({ budget }: { budget: BudgetStatus }) {
  const warnings = budgetWarnings(budget);
  if (warnings.length === 0) return null;
  const over = budget.level === "over";
  return (
    <div
      className={
        over
          ? "rounded-xl border border-danger/40 bg-danger/10 px-4 py-2.5 text-xs text-danger"
          : "rounded-xl border border-warning/40 bg-warning/10 px-4 py-2.5 text-xs text-warning"
      }
    >
      <span className="font-medium">{over ? "Monthly budget reached" : "Approaching the monthly budget"}</span>
      {" — "}
      {warnings.join(" · ")}. Reviews still run; raise the cap in Analytics when you mean to keep
      going.
    </div>
  );
}

const statusTone = (status: CodeReviewSummary["status"]) =>
  status === "applied"
    ? ("success" as const)
    : status === "failed"
      ? ("danger" as const)
      : status === "in_discussion"
        ? ("warning" as const)
        : status === "running"
          ? ("warning" as const)
          : ("accent" as const);

const statusLabel = (status: CodeReviewSummary["status"]) =>
  status === "applied"
    ? "Applied"
    : status === "failed"
      ? "Failed"
      : status === "in_discussion"
        ? "In discussion"
        : status === "running"
          ? "Running"
          : "Draft";

export function DashboardPage() {
  const [reviews, setReviews] = useState<CodeReviewSummary[]>([]);
  const [analytics, setAnalytics] = useState<AnalyticsResponse | null>(null);
  const [watches, setWatches] = useState<ReviewWatch[]>([]);
  const [watchBusyId, setWatchBusyId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [list, usage, watched] = await Promise.all([
        api.listReviews(),
        api.getAnalytics(30),
        api.listWatches(),
      ]);
      setReviews(list);
      setAnalytics(usage);
      setWatches(watched);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load reviews");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const toggleWatch = async (watch: ReviewWatch, enabled: boolean) => {
    setWatchBusyId(watch.id);
    setError(null);
    try {
      const updated = await api.updateWatch(watch.id, enabled);
      setWatches((current) => current.map((row) => (row.id === updated.id ? updated : row)));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update the watch.");
    } finally {
      setWatchBusyId(null);
    }
  };

  const deleteWatch = async (watch: ReviewWatch) => {
    setWatchBusyId(watch.id);
    setError(null);
    try {
      await api.deleteWatch(watch.id);
      setWatches((current) => current.filter((row) => row.id !== watch.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not delete the watch.");
    } finally {
      setWatchBusyId(null);
    }
  };

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Reviews</h1>
          <p className="text-sm text-inkMuted">
            Every pull request you have reviewed here, with the model used and its current state.
          </p>
        </div>
        <Button variant="secondary" onClick={() => void load()} disabled={loading}>
          <RefreshCw className="h-4 w-4" /> Refresh
        </Button>
      </header>

      <NewReviewPanel />

      {analytics ? (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-surfaceMuted/40 px-4 py-2.5 text-xs">
            <span className="text-inkMuted">
              <span className="font-medium text-ink">30-day activity</span>
              {" — "}
              {estimatedCost(analytics.totals.estimated_cost_usd)} est. spend ·{" "}
              {compactNumber(analytics.totals.total_tokens)} tokens ·{" "}
              {formatPercent(analytics.quality.acceptance_rate)} acceptance ·{" "}
              {formatDuration(analytics.latency.median_ms)} median latency
            </span>
            <Link
              to="/analytics"
              className="inline-flex items-center gap-1 text-accent transition-colors hover:text-accentStrong"
            >
              View full analytics <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
          <BudgetAlert budget={analytics.budget} />
        </div>
      ) : null}

      <WatchesPanel
        watches={watches}
        busyId={watchBusyId}
        onToggle={(watch, enabled) => void toggleWatch(watch, enabled)}
        onDelete={(watch) => void deleteWatch(watch)}
      />

      <Card>
        <CardHeader
          icon={<GitPullRequest className="h-4 w-4" />}
          title="Review history"
          description="Open a review to read the findings and discuss them with the model."
        />
        <CardBody>
          {loading ? (
            <p className="flex items-center gap-2 text-sm text-inkMuted">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading reviews…
            </p>
          ) : error ? (
            <p className="text-sm text-danger">{error}</p>
          ) : reviews.length === 0 ? (
            <div className="rounded-xl border border-dashed border-borderStrong/70 p-8 text-center">
              <p className="text-sm text-ink">No reviews yet</p>
              <p className="mt-1 text-xs text-inkMuted">
                Paste a pull request URL above, pick a model, and the findings land here.
              </p>
              <Link to="/settings">
                <Button className="mt-4" variant="secondary" size="sm">
                  Open settings
                </Button>
              </Link>
            </div>
          ) : (
            <div className="overflow-hidden rounded-xl border border-border">
              <table className="w-full text-left text-sm">
                <thead className="bg-surfaceMuted/60 text-xs uppercase tracking-wide text-inkMuted">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">Pull request</th>
                    <th className="px-4 py-2.5 font-medium">Repository</th>
                    <th className="px-4 py-2.5 font-medium">Model</th>
                    <th className="px-4 py-2.5 font-medium">Status</th>
                    <th className="px-4 py-2.5 font-medium">Created</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {reviews.map((review) => (
                    <tr key={review.id} className="transition-colors hover:bg-surfaceMuted/40">
                      <td className="px-4 py-3">
                        <Link to={`/reviews/${review.id}`} className="hover:text-accent">
                          <span className="font-medium text-ink">
                            {review.pr_title ?? `PR #${review.pr_number ?? review.id}`}
                          </span>
                          {review.pr_number ? (
                            <span className="ml-2 text-xs text-inkMuted">#{review.pr_number}</span>
                          ) : null}
                        </Link>
                        {review.parent_review_id ? (
                          <Link
                            to={`/reviews/${review.parent_review_id}`}
                            className="ml-2 text-[11px] text-accent transition-colors hover:text-accentStrong"
                            title="A watch started this review for the commits added since that one."
                          >
                            Continues #{review.parent_review_id}
                          </Link>
                        ) : null}
                      </td>
                      <td className="px-4 py-3 text-inkMuted">{review.repo_full_name ?? "—"}</td>
                      <td className="px-4 py-3 font-mono text-xs text-inkMuted">
                        {review.model_used ?? "—"}
                      </td>
                      <td className="px-4 py-3">
                        <Badge tone={statusTone(review.status)}>{statusLabel(review.status)}</Badge>
                      </td>
                      <td className="px-4 py-3 text-xs text-inkMuted">
                        {relativeTime(review.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
