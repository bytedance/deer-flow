import { PluginPage } from "@/components/workspace/plugin-page";

export default async function ExtensionPage({
  params,
  searchParams,
}: {
  params: Promise<{ namespace: string; surface_id: string }>;
  searchParams: Promise<{ thread?: string | string[] }>;
}) {
  const { namespace, surface_id } = await params;
  const { thread } = await searchParams;
  const threadId = typeof thread === "string" && thread.length <= 128 ? thread : undefined;
  return <PluginPage namespace={namespace} surfaceId={surface_id} threadId={threadId} />;
}
