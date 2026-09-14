import { AdminOnlyGate } from "@/components/dashboard/admin-only-gate";
import { ApiKeyPolicyPanel } from "@/components/dashboard/api-key-policy-panel";
import { SiteSettingsForm } from "@/components/dashboard/site-settings-form";

export default function SiteSettingsPage() {
  return (
    <AdminOnlyGate>
      <div className="space-y-8">
        <SiteSettingsForm />
        <ApiKeyPolicyPanel />
      </div>
    </AdminOnlyGate>
  );
}
