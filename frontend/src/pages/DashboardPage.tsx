import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { GitPullRequest, Loader2, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { NewReviewPanel } from "@/components/NewReviewPanel";
import { api, ApiError } from "@/services/api";
import { relativeTime } from "@/lib/utils";
import type { CodeReviewSummary } from "@/types";

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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setReviews(await api.listReviews());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load reviews");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

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
