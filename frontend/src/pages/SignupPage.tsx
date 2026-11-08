import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { AuthForm } from "@/components/AuthForm";
import { Input, Label } from "@/components/ui/Input";
import { useAuth } from "@/context/AuthContext";
import { ApiError } from "@/services/api";

export function SignupPage() {
  const { user, signup } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmation, setConfirmation] = useState("");

  if (user) return <Navigate to="/" replace />;

  async function submit(email: string, password: string) {
    setError(null);
    if (password !== confirmation) {
      setError("The two passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await signup(email, password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the account.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthForm
      mode="signup"
      title="Create an account"
      subtitle="Each account keeps its own GitHub/GitLab tokens, model keys and reviews."
      submitLabel="Create account"
      busyLabel="Creating…"
      busy={busy}
      error={error}
      passwordHint="At least 8 characters. Stored as a salted PBKDF2-SHA256 hash."
      onSubmit={submit}
      footer={
        <>
          Already have an account?{" "}
          <Link to="/login" className="text-accent hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <div className="space-y-1.5">
        <Label htmlFor="confirm-password">Confirm password</Label>
        <Input
          id="confirm-password"
          type="password"
          autoComplete="new-password"
          required
          minLength={8}
          value={confirmation}
          onChange={(event) => setConfirmation(event.target.value)}
          placeholder="Repeat the password"
        />
      </div>
    </AuthForm>
  );
}
