import { useCallback, useEffect, useState } from "react";
import { Plus, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Input, Label, Select } from "@/components/ui/Input";
import { api, ApiError } from "@/services/api";
import { relativeTime } from "@/lib/utils";
import type { Foundation, ModelOption, ReviewPolicy } from "@/types";

const INVOLVEMENTS: { value: ReviewPolicy["involvement"]; label: string }[] = [
  { value: "reviewer", label: "Review requested from me" },
  { value: "assignee", label: "Assigned to me" },
  { value: "author", label: "I am the author" },
  { value: "any", label: "Any involvement" },
];

const emptyForm = {
  repo_pattern: "",
  involvement: "reviewer" as ReviewPolicy["involvement"],
  model: "",
  foundation: "",
  max_active: 1,
};

/** Standing policies: evaluated by the watch tick against the inbox cache, not by a new scheduler. */
export function PoliciesPanel() {
  const [policies, setPolicies] = useState<ReviewPolicy[]>([]);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [foundations, setFoundations] = useState<Foundation[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [rows, catalog, skills] = await Promise.all([
        api.listPolicies(),
        api.listModels(),
        api.listSkills(),
      ]);
      setPolicies(rows);
      setModels(catalog.models);
      setFoundations(skills.foundations);
      setForm((current) => ({
        ...current,
        model: current.model || catalog.preferred || catalog.models[0]?.id || "",
        foundation: current.foundation || skills.default || skills.foundations[0]?.id || "",
      }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load policies");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function create() {
    if (!form.repo_pattern.trim() || !form.model) {
      setError("Add a repository and pick a model.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await api.createPolicy({
        repo_pattern: form.repo_pattern.trim(),
        involvement: form.involvement,
        model: form.model,
        skill_foundation: form.foundation || null,
        max_active: form.max_active,
      });
      setPolicies((current) => [created, ...current]);
      setForm((current) => ({ ...current, repo_pattern: "" }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the policy");
    } finally {
      setBusy(false);
    }
  }

  async function toggle(policy: ReviewPolicy) {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.updatePolicy(policy.id, { enabled: !policy.enabled });
      setPolicies((current) => current.map((row) => (row.id === updated.id ? updated : row)));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update the policy");
    } finally {
      setBusy(false);
    }
  }

  async function remove(policy: ReviewPolicy) {
    setBusy(true);
    setError(null);
    try {
      await api.deletePolicy(policy.id);
      setPolicies((current) => current.filter((row) => row.id !== policy.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not delete the policy");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader
        icon={<ShieldCheck className="h-4 w-4" />}
        title="Standing policies"
        description="Review PRs in a repository as they arrive in your inbox. Runs on the watch tick, never on its own scheduler."
        action={
          <Button variant="secondary" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={loading ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} /> Refresh
          </Button>
        }
      />
      <CardBody className="space-y-4">
        {error ? (
          <p className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">
            {error}
          </p>
        ) : null}

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="policy-repo">Repository</Label>
            <Input
              id="policy-repo"
              value={form.repo_pattern}
              placeholder="owner/repo or owner/*"
              onChange={(event) => setForm({ ...form, repo_pattern: event.target.value })}
            />
            <p className="text-[11px] text-inkMuted">
              One explicit repository is the safe default; a glob is a deliberate widening.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="policy-involvement">Involvement</Label>
            <Select
              id="policy-involvement"
              value={form.involvement}
              onChange={(event) =>
                setForm({ ...form, involvement: event.target.value as ReviewPolicy["involvement"] })
              }
            >
              {INVOLVEMENTS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="policy-model">Model</Label>
            <Select
              id="policy-model"
              value={form.model}
              onChange={(event) => setForm({ ...form, model: event.target.value })}
            >
              {models.map((model) => (
                <option key={model.id} value={model.id} disabled={!model.available}>
                  {model.label}
                  {model.available ? "" : " (unavailable)"}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="policy-foundation">Skill foundation</Label>
            <Select
              id="policy-foundation"
              value={form.foundation}
              onChange={(event) => setForm({ ...form, foundation: event.target.value })}
            >
              {foundations.map((foundation) => (
                <option key={foundation.id} value={foundation.id}>
                  {foundation.label}
                  {foundation.is_default ? " (default)" : ""}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="policy-max">At most active at once</Label>
            <Input
              id="policy-max"
              type="number"
              min={1}
              max={10}
              value={form.max_active}
              onChange={(event) =>
                setForm({ ...form, max_active: Math.max(1, Number(event.target.value) || 1) })
              }
            />
          </div>
          <div className="flex items-end">
            <Button onClick={() => void create()} disabled={busy}>
              <Plus className="h-4 w-4" /> Add policy
            </Button>
          </div>
        </div>

        {policies.length === 0 ? (
          <p className="text-xs text-inkMuted">
            No standing policies. Nothing is reviewed until you open a review yourself.
          </p>
        ) : (
          <ul className="divide-y divide-border rounded-xl border border-border">
            {policies.map((policy) => (
              <li key={policy.id} className="space-y-1 px-3 py-2.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="font-mono text-xs text-ink">{policy.repo_pattern}</span>
                    <Badge tone={policy.enabled ? "success" : "neutral"}>
                      {policy.enabled ? "Enabled" : "Paused"}
                    </Badge>
                    <span className="text-xs text-inkMuted">
                      {policy.involvement} · {policy.model_used} · {policy.skill_foundation ?? "default"}{" "}
                      · max {policy.max_active}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => void toggle(policy)}
                      disabled={busy}
                    >
                      {policy.enabled ? "Pause" : "Enable"}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Delete policy for ${policy.repo_pattern}`}
                      onClick={() => void remove(policy)}
                      disabled={busy}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
                <p className="text-[11px] text-inkMuted">
                  {policy.last_run_at ? `Last run ${relativeTime(policy.last_run_at)}` : "Not run yet"}
                  {policy.last_error ? ` — ${policy.last_error}` : ""}
                </p>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}
