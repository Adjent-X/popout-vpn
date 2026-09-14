import { AdminOnlyGate } from "@/components/dashboard/admin-only-gate";
import { AttacksDashboard } from "@/components/dashboard/attacks-dashboard";

export default function AttacksPage() {
  return (
    <AdminOnlyGate>
      <AttacksDashboard />
    </AdminOnlyGate>
  );
}
