import { SharePage } from "@/components/shares/share-page";

export default async function Page({
  params,
}: {
  params: Promise<{ share_token: string }>;
}) {
  const { share_token } = await params;
  return <SharePage key={share_token} token={share_token} />;
}
