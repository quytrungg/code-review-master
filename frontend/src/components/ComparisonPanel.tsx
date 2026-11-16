import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { GitCompareArrows, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Select } from "@/components/ui/Input";
import { api, ApiError } from "@/services/api";
import { compactNumber, estimatedCost } from "@/lib/utils";
import type { CodeReviewDetail, ComparisonEstimate, ComparisonRead, ModelOption } from "@/types";

function Bucket({
  title,
  tone,
  children,
}: {
  title: string;
  tone: "success" | "accent" | "warning";
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <p className="flex items-center gap-2 text-xs font-medium text-ink">
        <Badge tone={tone}>{title}</Badge>
      </p>
      <ul className="divide-y divide-border rounded-xl border border-border">{children}</ul>
    </div>
  );
}

/** "Compare with…" on a normal review, and the merged two-model view on either side of a pair. */
export function ComparisonPanel({ review }: { review: CodeReviewDetail }) {
  const navigate = useNavigate();
  const [comparison, setComparison] = useState<ComparisonRead | null>(null);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [model, setModel] = useState("");
  const [estimate, setEstimate] = useState<ComparisonEstimate | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isComparison = review.trigger === "comparison";

  useEffect(() => {
    let cancelled = false;
    api
      .getComparison(review.id)
      .then((data) => {
        if (!cancelled) setComparison(data);
      })
      .catch((err) => {
        if (!cancelled && !(err instanceof ApiError && err.status === 404)) {
          setError(err instanceof ApiError ? err.message : "Could not load the comparison");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [review.id]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    api
      .listModels()
      .then((catalog) => {
        if (cancelled) return;
        setModels(catalog.models);
        const candidate =
          catalog.models.find((item) => item.available && item.id !== review.model_used)?.id ??
          catalog.models[0]?.id ??
          "";
        setModel((current) => current || candidate);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [open, review.model_used]);

  useEffect(() => {
    if (!open || !model) return;
    let cancelled = false;
    setEstimate(null);
    api
      .estimateComparison(review.id, model)
      .then((data) => {
        if (!cancelled) setEstimate(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Could not estimate the run");
      });
    return () => {
      cancelled = true;
    };
  }, [open, model, review.id]);

  async function start() {
    if (!model) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.compareReview(review.id, model);
      navigate(`/reviews/${created.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start the comparison");
      setBusy(false);
    }
  }

  if (comparison) {
    return (
      <Card>
        <CardHeader
          icon={<GitCompareArrows className="h-4 w-4" />}
          title="Model comparison"
          description={`Findings within ${comparison.line_tolerance} line(s) with the same normalised key are shown as both. Evidence, not a score.`}
        />
        <CardBody className="space-y-4">
          <p className="text-xs text-inkMuted">
            <Link to={`/reviews/${comparison.primary.id}`} className="text-accent hover:text-accentStrong">
              Review #{comparison.primary.id} · {comparison.primary.model_used ?? "unknown model"}
            </Link>{" "}
            ({comparison.primary.thread_count} finding(s)) versus{" "}
            <Link
              to={`/reviews/${comparison.comparison.id}`}
              className="text-accent hover:text-accentStrong"
            >
              review #{comparison.comparison.id} · {comparison.comparison.model_used ?? "unknown model"}
            </Link>{" "}
            ({comparison.comparison.thread_count} finding(s)).
          </p>
          {comparison.both.length === 0 &&
          comparison.primary_only.length === 0 &&
          comparison.comparison_only.length === 0 ? (
            <p className="text-xs text-inkMuted">
              Neither run has findings yet. The comparison fills in as each review finishes.
            </p>
          ) : null}
          {comparison.both.length > 0 ? (
            <Bucket title={`Both models (${comparison.both.length})`} tone="success">
              {comparison.both.map((item) => (
                <li key={item.primary_thread_id} className="space-y-1 px-3 py-2 text-xs">
                  <span className="font-mono text-ink">
                    {item.file_path}:{item.primary_line}
                    {item.primary_line !== item.comparison_line ? ` / ${item.comparison_line}` : ""}
                  </span>
                  <p className="text-inkMuted">{item.snippet}</p>
                </li>
              ))}
            </Bucket>
          ) : null}
          {comparison.primary_only.length > 0 ? (
            <Bucket title={`Only review #${comparison.primary.id}`} tone="accent">
              {comparison.primary_only.map((item) => (
                <li key={item.thread_id} className="space-y-1 px-3 py-2 text-xs">
                  <span className="font-mono text-ink">
                    {item.file_path}:{item.line_number}
                  </span>
                  <p className="text-inkMuted">{item.snippet}</p>
                </li>
              ))}
            </Bucket>
          ) : null}
          {comparison.comparison_only.length > 0 ? (
            <Bucket title={`Only review #${comparison.comparison.id}`} tone="warning">
              {comparison.comparison_only.map((item) => (
                <li key={item.thread_id} className="space-y-1 px-3 py-2 text-xs">
                  <span className="font-mono text-ink">
                    {item.file_path}:{item.line_number}
                  </span>
                  <p className="text-inkMuted">{item.snippet}</p>
                </li>
              ))}
            </Bucket>
          ) : null}
        </CardBody>
      </Card>
    );
  }

  if (isComparison) return null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="secondary" size="sm" onClick={() => setOpen((value) => !value)}>
        <GitCompareArrows className="h-3.5 w-3.5" /> {open ? "Cancel comparison" : "Compare with…"}
      </Button>
      {open ? (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-surfaceMuted/40 px-3 py-2">
          <Select
            value={model}
            onChange={(event) => setModel(event.target.value)}
            aria-label="Second model"
            className="h-8 w-64 text-xs"
          >
            {models.map((option) => (
              <option key={option.id} value={option.id} disabled={!option.available}>
                {option.label}
                {option.id === review.model_used ? " (current)" : ""}
              </option>
            ))}
          </Select>
          <span className="text-[11px] text-inkMuted">
            {estimate ? (
              <>
                {estimatedCost(estimate.estimated_cost_usd)} ·{" "}
                {compactNumber(estimate.prompt_tokens + estimate.completion_tokens)} est. tokens
              </>
            ) : (
              <span className="inline-flex items-center gap-1">
                <Loader2 className="h-3 w-3 animate-spin" /> Estimating…
              </span>
            )}
          </span>
          <Button size="sm" onClick={() => void start()} disabled={busy || !model}>
            {busy ? "Starting…" : "Start comparison"}
          </Button>
        </div>
      ) : null}
      {error ? <span className="text-xs text-danger">{error}</span> : null}
      {estimate && open ? (
        <p className="w-full text-[11px] text-inkMuted">{estimate.note} This run is estimated, not billed.</p>
      ) : null}
    </div>
  );
}
