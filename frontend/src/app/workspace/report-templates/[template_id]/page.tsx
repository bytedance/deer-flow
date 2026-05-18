import { ReportTemplateDetailPage } from "@/components/workspace/report-templates/report-template-detail-page";

interface Props {
  params: Promise<{ template_id: string }>;
}

export default async function Page({ params }: Props) {
  const { template_id } = await params;
  return <ReportTemplateDetailPage templateId={template_id} />;
}
