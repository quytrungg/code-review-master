import { useEffect, useState } from "react";
import { Loader2, Play, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Label, Select } from "@/components/ui/Input";
import { api, ApiError } from "@/services/api";
import type { CachedPR, Foundation, ModelOption } from "@/types";

const PROVIDER_LABEL: Record<ModelOption["provider"], string> = {
  claude: "claude",
  openai: "openai",
  "ollama-cloud": "ollama cloud",
  "ollama-local": "local",
};

/**
 * The dialog opened by the inbox's AI review button. Owns the catalog and create-review calls;
 * the page only owns open/close state.
 */
export function StartReviewModal({
  pr,
  onClose,
  onStarted,
}: {
  pr: CachedPR;
  onClose: () => void;
  onStarted: (reviewId: number) => void;
}) {
  const [models, setModels] = useState<ModelOption[]>([]);
  const [model, setModel] = useState("");
  const [foundations, setFoundations] = useState<Foundation[]>([]);
  const [foundation, setFoundation] = useState("");
  const [defaultFoundation, setDefaultFoundation] = useState("");
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([api.listModels(), api.listSkills()])
      .then(([catalog, skills]) => {
        if (cancelled) return;
        setModels(catalog.models);
        setModel(catalog.preferred ?? catalog.models.find((option) => option.available)?.id ?? "");
        setFoundations(skills.foundations);
        setDefaultFoundation(skills.default);
        setFoundation((current) => current || skills.default);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Could not load models and skills.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function start() {
    setStarting(true);
    setError(null);
    try {
      const review = await api.createReview(pr.pr_url, model, foundation);
      onStarted(review.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start the review.");
      setStarting(false);
    }
  }

  const selected = models.find((option) => option.id === model);
  const canStart = Boolean(model && foundation && selected?.available) && !starting;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <button
        type="button"
        aria-label="Close start review"
        className="absolute inset-0 bg-canvas/60 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="relative w-full max-w-md space-y-4 rounded-xl border border-border bg-surface p-5 shadow-2xl">
        <header className="flex items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <h2 className="text-sm font-semibold text-ink">Start AI review</h2>
            <p className="truncate text-xs text-inkMuted">
              {pr.repo_owner}/{pr.repo_name} #{pr.pr_number} · {pr.title}
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close" disabled={starting}>
            <X className="h-4 w-4" />
          </Button>
        </header>

        {loading ? (
          <p className="flex items-center gap-2 text-sm text-inkMuted">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading models and skills…
          </p>
        ) : (
          <>
            <div className="space-y-2">
              <Label htmlFor="start-review-model">Model</Label>
              <Select
                id="start-review-model"
                value={model}
                onChange={(event) => setModel(event.target.value)}
                disabled={starting || models.length === 0}
              >
                {model === "" ? (
                  <option value="">{models.length === 0 ? "No providers configured" : "Select a model"}</option>
                ) : null}
                {models.map((option) => (
                  <option key={option.id} value={option.id} disabled={!option.available}>
                    {option.label} · {PROVIDER_LABEL[option.provider]}
                    {option.available ? "" : ` (${option.note ?? "unavailable"})`}
                  </option>
                ))}
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="start-review-foundation">Skill foundation</Label>
              <Select
                id="start-review-foundation"
                value={foundation}
                onChange={(event) => setFoundation(event.target.value)}
                disabled={starting || foundations.length === 0}
              >
                {foundations.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.id}
                    {item.id === defaultFoundation ? " (default)" : ""} · {item.file_count} file(s)
                  </option>
                ))}
              </Select>
            </div>
          </>
        )}

        {error ? <p className="text-xs text-danger">{error}</p> : null}

        <footer className="flex justify-end gap-2 border-t border-border pt-4">
          <Button variant="ghost" onClick={onClose} disabled={starting}>
            Cancel
          </Button>
          <Button onClick={() => void start()} disabled={!canStart}>
            {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {starting ? "Starting…" : "Start review"}
          </Button>
        </footer>
      </div>
    </div>
  );
}
