import { PluginPage } from "@/components/workspace/plugin-page";
import { threadIdFromQuery } from "@/core/extensions/pages";

export default async function ExtensionPage({
  params,
  searchParams,
}: {
  params: Promise<{ namespace: string; surface_id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const [{ namespace, surface_id }, query] = await Promise.all([
    params,
    searchParams,
  ]);
  return (
    <PluginPage
      namespace={namespace}
      surfaceId={surface_id}
      threadId={threadIdFromQuery(query.thread)}
    />
  );
}
