import { useCallback, useEffect, useState } from "react";
import { BarChart3, Coins, Gauge, Loader2, RefreshCw, Target } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Input, Label, Select } from "@/components/ui/Input";
import { compactNumber, estimatedCost, formatDuration, formatPercent } from "@/lib/utils";
import { api, ApiError } from "@/services/api";
import type { AnalyticsResponse, BudgetStatus, ModelUsage, PurposeUsage } from "@/types";

const WINDOWS = [7, 30, 90];

const PURPOSE_LABELS: Record<PurposeUsage["purpose"], string> = {
  ingest: "Ingest",
  discuss: "Discuss",
  verdict: "Verdict",
  summarise: "Summarise",
};

function Kpi({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <Card>
      <div className="space-y-1 p-4">
        <p className="text-[11px] uppercase tracking-wide text-inkMuted">{label}</p>
        <p className="text-lg font-semibold tabular-nums text-ink">{value}</p>
        <p className="text-xs text-inkMuted">{hint}</p>
      </div>
    </Card>
  );
}

function shortModel(row: ModelUsage): string {
  return row.model.startsWith(`${row.provider}:`)
    ? row.model.slice(row.provider.length + 1)
    : row.model;
}

function BudgetManager({
  budget,
  onSaved,
}: {
  budget: BudgetStatus;
  onSaved: () => Promise<void>;
}) {
  const [tokens, setTokens] = useState("");
  const [dollars, setDollars] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    setTokens(budget.token_budget === null ? "" : String(budget.token_budget));
    setDollars(budget.dollar_budget === null ? "" : String(budget.dollar_budget));
  }, [budget.token_budget, budget.dollar_budget]);

  async function save() {
    const tokenValue = tokens.trim() === "" ? null : Number(tokens);
    const dollarValue = dollars.trim() === "" ? null : Number(dollars);
    const invalid =
      (tokenValue !== null && (!Number.isFinite(tokenValue) || tokenValue < 0)) ||
      (dollarValue !== null && (!Number.isFinite(dollarValue) || dollarValue < 0));
    if (invalid) {
      setError("Budgets must be positive numbers. Leave a field empty for no cap.");
      return;
    }

    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await api.updateSettings({
        monthly_token_budget: tokenValue,
        monthly_dollar_budget: dollarValue,
      });
      await onSaved();
      setNotice("Budget saved.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the budget");
    } finally {
      setSaving(false);
    }
  }

  const levelTone =
    budget.level === "over" ? ("danger" as const) : budget.level === "warn" ? ("warning" as const) : ("neutral" as const);
  const levelLabel =
    budget.level === "over" ? "Over budget" : budget.level === "warn" ? "Near the cap" : "Within budget";

  return (
    <Card>
      <CardHeader
        icon={<Coins className="h-4 w-4" />}
        title="Monthly budget"
        description={`Soft caps for ${budget.month}. They warn, they never block a review.`}
        action={<Badge tone={levelTone}>{levelLabel}</Badge>}
      />
      <CardBody>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="token-budget">Token cap</Label>
            <Input
              id="token-budget"
              inputMode="numeric"
              placeholder="No cap"
              value={tokens}
              onChange={(event) => setTokens(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="dollar-budget">Dollar cap (USD)</Label>
            <Input
              id="dollar-budget"
              inputMode="decimal"
              placeholder="No cap"
              value={dollars}
              onChange={(event) => setDollars(event.target.value)}
            />
          </div>
        </div>

        <dl className="grid gap-2 text-xs text-inkMuted sm:grid-cols-2">
          <div className="flex items-baseline justify-between rounded-lg border border-border/70 px-3 py-2">
            <dt>Tokens this month</dt>
            <dd className="font-mono text-ink">
              {compactNumber(budget.tokens_used)}
              {budget.token_pct === null ? "" : ` · ${formatPercent(budget.token_pct)}`}
            </dd>
          </div>
          <div className="flex items-baseline justify-between rounded-lg border border-border/70 px-3 py-2">
            <dt>Estimated spend</dt>
            <dd className="font-mono text-ink">
              {estimatedCost(budget.dollars_used)}
              {budget.dollar_pct === null ? "" : ` · ${formatPercent(budget.dollar_pct)}`}
            </dd>
          </div>
        </dl>

        <p className="text-xs text-inkMuted">
          An amber banner appears at 80% of a cap, red at 100%. Alerts are advisory; the next review
          still runs.
        </p>

        {error ? <p className="text-xs text-danger">{error}</p> : null}
        {notice ? <p className="text-xs text-success">{notice}</p> : null}

        <Button size="sm" onClick={() => void save()} disabled={saving}>
          {saving ? "Saving…" : "Save budget"}
        </Button>
      </CardBody>
    </Card>
  );
}

export function AnalyticsPage() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await api.getAnalytics(days));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load analytics");
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    void load();
  }, [load]);

  const purposes = data?.by_purpose ?? [];
  const busiest = Math.max(1, ...purposes.map((row) => row.calls));

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-xl font-semibold tracking-tight">Analytics</h1>
          <p className="text-sm text-inkMuted">
            Spend, volume and review quality across every model call. Counts are exact; money is an
            estimate from a local price table.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select
            aria-label="Window"
            className="w-32"
            value={String(days)}
            onChange={(event) => setDays(Number(event.target.value))}
          >
            {WINDOWS.map((window) => (
              <option key={window} value={window}>
                Last {window} days
              </option>
            ))}
          </Select>
          <Button variant="secondary" onClick={() => void load()} disabled={loading}>
            <RefreshCw className="h-4 w-4" /> Refresh
          </Button>
        </div>
      </header>

      {error ? (
        <p className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">
          {error}
        </p>
      ) : null}

      {loading && !data ? (
        <p className="flex items-center gap-2 text-sm text-inkMuted">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading analytics…
        </p>
      ) : null}

      {data ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Kpi
              label={`Estimated spend (${data.window_days}d)`}
              value={estimatedCost(data.totals.estimated_cost_usd)}
              hint={`${data.totals.priced_calls} of ${data.totals.calls} calls priced`}
            />
            <Kpi
              label="Tokens processed"
              value={compactNumber(data.totals.total_tokens)}
              hint={`in ${compactNumber(data.totals.prompt_tokens)} · out ${compactNumber(
                data.totals.completion_tokens,
              )}`}
            />
            <Kpi
              label="Median / p95 latency"
              value={`${formatDuration(data.latency.median_ms)} / ${formatDuration(data.latency.p95_ms)}`}
              hint={`avg ${formatDuration(data.latency.avg_ms)} · ${data.totals.failed_calls} failed`}
            />
            <Kpi
              label="Acceptance rate"
              value={formatPercent(data.quality.acceptance_rate)}
              hint={
                data.quality.findings === 0
                  ? "No AI findings in this window"
                  : `${data.quality.accepted} of ${data.quality.findings} findings · ${formatPercent(
                      data.quality.pushback_rate,
                    )} push-back`
              }
            />
          </div>

          <Card>
            <CardHeader
              icon={<BarChart3 className="h-4 w-4" />}
              title="Model comparison"
              description="Acceptance counts AI findings whose latest round was published; push-back counts the ones the reviewer engaged with or discarded."
            />
            <CardBody>
              {data.by_model.length === 0 ? (
                <p className="rounded-xl border border-dashed border-borderStrong/70 p-6 text-center text-xs text-inkMuted">
                  No model calls in this window yet. Run a review and its calls land here.
                </p>
              ) : (
                <div className="overflow-x-auto rounded-xl border border-border">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-surfaceMuted/60 text-xs uppercase tracking-wide text-inkMuted">
                      <tr>
                        <th className="px-3 py-2.5 font-medium">Model</th>
                        <th className="px-3 py-2.5 font-medium">Provider</th>
                        <th className="px-3 py-2.5 text-right font-medium">Calls</th>
                        <th className="px-3 py-2.5 text-right font-medium">Tokens in / out</th>
                        <th className="px-3 py-2.5 text-right font-medium">Est. cost</th>
                        <th className="px-3 py-2.5 text-right font-medium">Avg latency</th>
                        <th className="px-3 py-2.5 text-right font-medium">Acceptance</th>
                        <th className="px-3 py-2.5 text-right font-medium">Push-back</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {data.by_model.map((row) => (
                        <tr key={row.model} className="hover:bg-surfaceMuted/40">
                          <td className="px-3 py-2.5 font-mono text-xs text-ink">{shortModel(row)}</td>
                          <td className="px-3 py-2.5 text-xs text-inkMuted">{row.provider}</td>
                          <td className="px-3 py-2.5 text-right tabular-nums">{row.calls}</td>
                          <td className="px-3 py-2.5 text-right font-mono text-xs text-inkMuted">
                            {compactNumber(row.prompt_tokens)} / {compactNumber(row.completion_tokens)}
                          </td>
                          <td className="px-3 py-2.5 text-right font-mono text-xs">
                            {estimatedCost(row.estimated_cost_usd)}
                          </td>
                          <td className="px-3 py-2.5 text-right text-xs text-inkMuted">
                            {formatDuration(row.avg_latency_ms)}
                          </td>
                          <td className="px-3 py-2.5 text-right text-xs">
                            {formatPercent(row.acceptance_rate)}
                            {row.findings > 0 ? (
                              <span className="ml-1 text-inkMuted">
                                ({row.accepted}/{row.findings})
                              </span>
                            ) : null}
                          </td>
                          <td className="px-3 py-2.5 text-right text-xs text-inkMuted">
                            {formatPercent(row.pushback_rate)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardBody>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader
                icon={<Gauge className="h-4 w-4" />}
                title="Purpose breakdown"
                description="Where the calls and tokens go across the review pipeline."
              />
              <CardBody>
                <ul className="space-y-3">
                  {purposes.map((row) => (
                    <li key={row.purpose} className="space-y-1">
                      <div className="flex items-baseline justify-between text-xs">
                        <span className="text-ink">{PURPOSE_LABELS[row.purpose]}</span>
                        <span className="font-mono text-inkMuted">
                          {row.calls} call{row.calls === 1 ? "" : "s"} · {compactNumber(row.total_tokens)} tokens ·{" "}
                          {estimatedCost(row.estimated_cost_usd)}
                        </span>
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-surfaceMuted">
                        <div
                          className="h-full rounded-full bg-accent/70"
                          style={{ width: `${Math.round((row.calls / busiest) * 100)}%` }}
                        />
                      </div>
                    </li>
                  ))}
                </ul>
                <p className="flex items-center gap-1.5 text-xs text-inkMuted">
                  <Target className="h-3.5 w-3.5" />
                  Verdict and summarise passes are advisory: a failure keeps the previous opinion or the
                  copilot's wording.
                </p>
              </CardBody>
            </Card>

            <BudgetManager budget={data.budget} onSaved={load} />
          </div>
        </>
      ) : null}
    </div>
  );
}
