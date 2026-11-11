import { Route, Routes } from "react-router-dom";
import { Navbar } from "@/components/Navbar";
import { RequireAuth } from "@/components/RequireAuth";
import { SetupGate } from "@/components/SetupGate";
import { AuthProvider } from "@/context/AuthContext";
import { SettingsProvider } from "@/context/SettingsContext";
import { AnalyticsPage } from "@/pages/AnalyticsPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { InboxPage } from "@/pages/InboxPage";
import { LoginPage } from "@/pages/LoginPage";
import { ReviewDetailPage } from "@/pages/ReviewDetailPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { SetupPage } from "@/pages/SetupPage";
import { SignupPage } from "@/pages/SignupPage";
import { SkillsPage } from "@/pages/SkillsPage";

/** Everything behind a session: nav, page routes, footer. */
function Workspace() {
  return (
    <div className="flex min-h-full flex-col">
      <Navbar />
      <main className="mx-auto w-full max-w-7xl flex-1 px-5 py-8">
        <Routes>
          <Route
            path="/"
            element={
              <SetupGate>
                <DashboardPage />
              </SetupGate>
            }
          />
          <Route path="/setup" element={<SetupPage />} />
          <Route path="/inbox" element={<InboxPage />} />
          <Route path="/skills" element={<SkillsPage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/reviews/:id" element={<ReviewDetailPage />} />
          <Route
            path="*"
            element={<p className="text-sm text-inkMuted">Nothing here. Head back to Reviews.</p>}
          />
        </Routes>
      </main>
      <footer className="border-t border-border/60 py-4 text-center text-xs text-inkMuted">
        Local-first · your tokens and code never leave this machine except for the model you choose.
      </footer>
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        {/* Signed-out users see /login; the settings fetch only happens once a session exists. */}
        <Route
          path="*"
          element={
            <RequireAuth>
              <SettingsProvider>
                <Workspace />
              </SettingsProvider>
            </RequireAuth>
          }
        />
      </Routes>
    </AuthProvider>
  );
}
