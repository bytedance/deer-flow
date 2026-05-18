import { ReportRunDetailPage } from "@/components/workspace/report-templates/report-run-detail-page";

interface Props {
  params: Promise<{ run_id: string }>;
}

export default async function Page({ params }: Props) {
  const { run_id } = await params;
  return <ReportRunDetailPage runId={run_id} />;
}
