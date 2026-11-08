import { AlertTriangle, Info, XCircle } from "lucide-react";

export function WarningsBanner({
  error,
  notes,
}: {
  error?: string | null;
  notes?: string | null;
}) {
  const warnings = (notes ?? "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  if (!error && warnings.length === 0) return null;

  return (
    <div className="space-y-2">
      {error ? (
        <div className="flex items-start gap-2 rounded-xl border border-danger/40 bg-danger/10 px-4 py-3 text-xs text-danger">
          <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p className="font-medium">The model call failed for this review</p>
            <p className="mt-0.5 whitespace-pre-wrap">{error}</p>
          </div>
        </div>
      ) : null}

      {warnings.length > 0 ? (
        <div className="rounded-xl border border-warning/30 bg-warning/5 px-4 py-3 text-xs text-warning">
          <p className="flex items-center gap-1.5 font-medium">
            <AlertTriangle className="h-3.5 w-3.5" /> Ingestion notes
          </p>
          <ul className="mt-1 space-y-0.5 text-warning/90">
            {warnings.map((warning) => (
              <li key={warning} className="flex items-start gap-1.5">
                <Info className="mt-0.5 h-3 w-3 shrink-0 opacity-70" />
                {warning}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
