import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Layers, Loader2, Play, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Input, Label, Select } from "@/components/ui/Input";
import { api, ApiError } from "@/services/api";
import type { Foundation, ModelOption } from "@/types";

const PROVIDER_LABEL: Record<ModelOption["provider"], string> = {
  claude: "claude",
  openai: "openai",
  "ollama-cloud": "ollama cloud",
  "ollama-local": "local",
};

export function NewReviewPanel() {
  const navigate = useNavigate();
  const [prUrl, setPrUrl] = useState("");
  const [model, setModel] = useState("");
  const [models, setModels] = useState<ModelOption[]>([]);
  const [foundations, setFoundations] = useState<Foundation[]>([]);
  const [foundation, setFoundation] = useState("");
  const [defaultFoundation, setDefaultFoundation] = useState("code-review");
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [loadingCatalog, setLoadingCatalog] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadCatalog = useCallback(async () => {
    setLoadingCatalog(true);
    setCatalogError(null);
    try {
      const [catalog, skills] = await Promise.all([api.listModels(), api.listSkills()]);
      setModels(catalog.models);
      setFoundations(skills.foundations);
      setDefaultFoundation(skills.default);
      setFoundation((current) => current || skills.default);
      const firstUsable = catalog.models.find((option) => option.available);
      setModel((current) => current || firstUsable?.id || "");
    } catch (err) {
      setCatalogError(err instanceof ApiError ? err.message : "Could not load models and skills");
    } finally {
      setLoadingCatalog(false);
    }
  }, []);

  useEffect(() => {
    void loadCatalog();
  }, [loadCatalog]);

  async function start() {
    setStarting(true);
    setError(null);
    try {
      const review = await api.createReview(prUrl.trim(), model, foundation);
      navigate(`/reviews/${review.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to start the review");
      setStarting(false);
    }
  }

  const selected = models.find((option) => option.id === model);
  const selectedFoundation = foundations.find((item) => item.id === foundation);
  const canStart =
    Boolean(prUrl.trim() && model && selected?.available && foundation) && !starting;

  return (
    <Card>
      <CardHeader
        icon={<Sparkles className="h-4 w-4" />}
        title="New code review"
        description="Paste a pull-request URL. Progress streams live once the review starts."
        action={
          <Badge tone="accent">
            <Layers className="h-3 w-3" />
            {selectedFoundation?.file_count ?? 0} skill file(s)
          </Badge>
        }
      />
      <CardBody>
        <div className="grid gap-4 lg:grid-cols-[2fr_1fr_1fr_auto] lg:items-end">
          <div className="space-y-2">
            <Label htmlFor="pr-url">Pull request URL</Label>
            <Input
              id="pr-url"
              placeholder="https://github.com/owner/repo/pull/123"
              value={prUrl}
              onChange={(event) => setPrUrl(event.target.value)}
              disabled={starting}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="model">Model</Label>
            {loadingCatalog ? (
              <div className="flex h-10 items-center gap-2 text-xs text-inkMuted">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading models…
              </div>
            ) : (
              <Select
                id="model"
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
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="foundation">Skill foundation</Label>
            <Select
              id="foundation"
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

          <Button className="h-10" onClick={() => void start()} disabled={!canStart}>
            {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {starting ? "Starting…" : "Start review"}
          </Button>
        </div>

        {catalogError ? (
          <p className="flex items-center gap-1.5 text-xs text-danger">
            <AlertTriangle className="h-3.5 w-3.5" /> {catalogError}
          </p>
        ) : models.length === 0 && !loadingCatalog ? (
          <p className="text-xs text-inkMuted">
            No models available. Add an Ollama Cloud key, a Claude key, or point at a local Ollama
            daemon in Settings, then reload this page.
          </p>
        ) : null}

        {error ? (
          <div className="rounded-lg border border-danger/40 bg-danger/10 p-3 text-xs text-danger">
            {error}
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}
