import { PluginPage } from "@/components/workspace/plugin-page";

export default async function ExtensionPage({
  params,
}: {
  params: Promise<{ namespace: string; surface_id: string }>;
}) {
  const { namespace, surface_id } = await params;
  return <PluginPage namespace={namespace} surfaceId={surface_id} />;
}
