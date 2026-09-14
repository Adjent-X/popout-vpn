import { AdminAccountsPanel } from "@/components/dashboard/admin-accounts-panel";
import { AdminOnlyGate } from "@/components/dashboard/admin-only-gate";
import { AdminTokensPanel } from "@/components/dashboard/admin-tokens-panel";

export default function AdminPage() {
  return (
    <AdminOnlyGate>
      <div className="dash-page">
        <div>
          <h1 className="dash-title">
            Admin
          </h1>
          <p className="dash-sub">
            Manage accounts and registration invite tokens.
          </p>
        </div>
        <AdminAccountsPanel />
        <AdminTokensPanel />
      </div>
    </AdminOnlyGate>
  );
}
