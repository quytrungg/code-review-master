import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function SplitPane({
  left,
  right,
  className,
}: {
  left: ReactNode;
  right: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("grid gap-4 lg:grid-cols-2", className)}>
      <section
        aria-label="Code context"
        className="max-h-[62vh] space-y-4 overflow-y-auto pr-1 lg:max-h-[64vh]"
      >
        <div className="label-text sticky top-0 z-10 bg-canvas/90 py-1 backdrop-blur">
          Code / context
        </div>
        {left}
      </section>
      <section
        aria-label="Discussion"
        className="max-h-[62vh] space-y-4 overflow-y-auto pr-1 lg:max-h-[64vh]"
      >
        <div className="label-text sticky top-0 z-10 bg-canvas/90 py-1 backdrop-blur">
          Discussion
        </div>
        {right}
      </section>
    </div>
  );
}
