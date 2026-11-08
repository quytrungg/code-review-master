import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useSettings } from "@/context/SettingsContext";

/**
 * Sends the dashboard to the setup guide until the app has a GitHub token and a model
 * provider. Only routes that cannot work unconfigured are wrapped; /settings and a
 * directly-opened review stay reachable.
 */
export function SetupGate({ children }: { children: ReactNode }) {
  const { settings, loading, error, refresh } = useSettings();

  if (loading) {
    return (
      <p className="flex items-center gap-2 text-sm text-inkMuted">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading configuration…
      </p>
    );
  }

  if (error) {
    return (
      <Card className="p-6">
        <p className="text-sm text-danger">{error}</p>
        <Button className="mt-3" variant="secondary" onClick={() => void refresh()}>
          Retry
        </Button>
      </Card>
    );
  }

  if (settings?.needs_setup) {
    return <Navigate to="/setup" replace />;
  }

  return <>{children}</>;
}
