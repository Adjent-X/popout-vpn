import { ApiKeysPanel } from "@/components/dashboard/api-keys-panel";
import { SettingsForm } from "@/components/dashboard/settings-form";

export default function SettingsPage() {
  return (
    <div className="space-y-8">
      <SettingsForm />
      <ApiKeysPanel />
    </div>
  );
}
