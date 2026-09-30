import { Suspense } from "react";

import { CapabilityCenter } from "@/components/workspace/capabilities/capability-center";

export default function CapabilitiesPage() {
  return (
    <Suspense>
      <CapabilityCenter />
    </Suspense>
  );
}
