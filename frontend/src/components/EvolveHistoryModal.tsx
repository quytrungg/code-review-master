import { useState } from "react";
import { Brain, Info } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Label, Select } from "@/components/ui/Input";
import { Modal } from "@/components/ui/Modal";
import type { Foundation, ModelOption } from "@/types";

/**
 * The starting point for a skill evolution run.
 *
 * It used to be a permanent card in the Skills page. It is a modal now because the choice is made
 * once per run, not read at a glance: the foundation and the model. The evidence is always the
 * review history — past reviews and the corrections in their comment threads — because local
 * CLI-agent session folders do not exist where this app is deployed.
 */
export function EvolveHistoryModal({
  foundations,
  models,
  defaultFoundation,
  defaultModel,
  onClose,
  onStart,
}: {
  foundations: Foundation[];
  models: ModelOption[];
  defaultFoundation: string;
  defaultModel: string;
  onClose: () => void;
  onStart: (choice: { foundation: string; model: string }) => void;
}) {
  const [foundation, setFoundation] = useState(defaultFoundation);
  const [model, setModel] = useState(defaultModel);

  const canStart = Boolean(foundation && model);

  return (
    <Modal
      title="Evolve from review history"
      description="Let a model read your last 30 days of pushbacks and propose edits to the guideline files."
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => onStart({ foundation, model })} disabled={!canStart}>
            <Brain className="h-4 w-4" /> Start analysis
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="space-y-1">
          <Label htmlFor="evolve-foundation">Skill foundation</Label>
          <Select
            id="evolve-foundation"
            value={foundation}
            onChange={(event) => setFoundation(event.target.value)}
          >
            {foundations.map((item) => (
              <option key={item.id} value={item.id}>
                {item.id}
                {item.is_default ? " (default)" : ""} · {item.file_count} file(s)
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-1">
          <Label htmlFor="evolve-model">Model</Label>
          <Select
            id="evolve-model"
            value={model}
            onChange={(event) => setModel(event.target.value)}
          >
            {model === "" ? (
              <option value="">
                {models.length === 0 ? "No providers configured" : "Select a model"}
              </option>
            ) : null}
            {models.map((option) => (
              <option key={option.id} value={option.id} disabled={!option.available}>
                {option.label}
                {option.available ? "" : ` (${option.note ?? "unavailable"})`}
              </option>
            ))}
          </Select>
          {models.length === 0 ? (
            <p className="text-xs text-inkMuted">Add a model key in Settings before running an analysis.</p>
          ) : null}
        </div>

        <p className="flex items-start gap-1.5 rounded-lg border border-border bg-canvas/40 px-3 py-2 text-[11px] text-inkMuted">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          This sends the foundation&apos;s rules and the last 30 days of review history — reviews and
          the corrections in their comment threads — to the model you chose.
        </p>
      </div>
    </Modal>
  );
}
