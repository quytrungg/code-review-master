import { useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { AuthForm } from "@/components/AuthForm";
import { useAuth } from "@/context/AuthContext";
import { ApiError } from "@/services/api";

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const from = (location.state as { from?: string } | null)?.from ?? "/";
  if (user) return <Navigate to={from} replace />;

  async function submit(email: string, password: string) {
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not sign in.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthForm
      mode="login"
      title="Sign in"
      subtitle="Your reviews, keys and discussions are scoped to this account."
      submitLabel="Sign in"
      busyLabel="Signing in…"
      busy={busy}
      error={error}
      onSubmit={submit}
      footer={
        <>
          No account yet?{" "}
          <Link to="/signup" className="text-accent hover:underline">
            Create one
          </Link>
        </>
      }
    />
  );
}
