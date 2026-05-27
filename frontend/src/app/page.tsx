import {
  ActivityIcon,
  ClipboardCheckIcon,
  LineChartIcon,
  type LucideIcon,
  MessageSquareIcon,
} from "lucide-react";
import Link from "next/link";

import { Footer } from "@/components/landing/footer";
import { Header } from "@/components/landing/header";
import { Button } from "@/components/ui/button";

const INDUSTRIAL_WORKFLOWS = [
  {
    label: "设备监测",
    description: "实时查看装置运行状态与关键测点数据。",
    path: "/workspace/agents/monitoring-analysis/chats/new",
    icon: ActivityIcon,
  },
  {
    label: "故障诊断",
    description: "基于振动频谱与趋势特征的故障识别与根因分析。",
    path: "/workspace/agents/device-diagnosis/chats/new",
    icon: ClipboardCheckIcon,
  },
  {
    label: "趋势报告",
    description: "日报、周报、月报由 AI 自动生成并导出。",
    path: "/workspace/agents/trend-report/chats/new",
    icon: LineChartIcon,
  },
] as const;

export default function LandingPage() {
  return (
    <div className="bg-background text-foreground min-h-screen w-full">
      <Header />
      <main className="container-md mx-auto flex w-full flex-col px-4 pt-32 pb-16 md:px-8">
        <section className="flex flex-col items-center gap-6 py-16 text-center">
          <h1 className="text-4xl font-bold tracking-tight md:text-6xl">
            EHM AI 工作台
          </h1>
          <p className="text-muted-foreground max-w-2xl text-lg md:text-xl">
            工业设备智能诊断与监测平台。
            <br />
            面向石油石化行业，以 AI 驱动实时监测、故障诊断与运行报告。
          </p>
          <div className="flex gap-3 mt-4">
            <Link href="/workspace/agents/monitoring-analysis/chats/new">
              <Button size="lg">开始监测</Button>
            </Link>
            <Link href="/workspace">
              <Button size="lg" variant="outline">
                进入工作台
              </Button>
            </Link>
          </div>
        </section>

        <section className="py-8">
          <h2 className="text-muted-foreground mb-4 text-center text-sm font-semibold uppercase tracking-wide">
            Quick Access
          </h2>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            {INDUSTRIAL_WORKFLOWS.map((workflow) => (
              <WorkflowCard
                key={workflow.path}
                label={workflow.label}
                description={workflow.description}
                path={workflow.path}
                icon={workflow.icon}
              />
            ))}
          </div>
        </section>

        <section className="grid grid-cols-1 gap-6 py-16 md:grid-cols-2 lg:grid-cols-4">
          <FeatureCard
            title="实时监测"
            description="装置运行状态、关键测点数据随时查询。"
          />
          <FeatureCard
            title="智能诊断"
            description="基于振动频谱、轴心轨迹、趋势特征的故障识别与根因分析。"
          />
          <FeatureCard
            title="运行报告"
            description="日报、周报、月报由 AI 自动生成，统一 Markdown 文档可导出。"
          />
          <FeatureCard
            title="对话操作"
            description="自然语言描述设备问题，系统调用专业技能完成分析与处置建议。"
          />
        </section>
      </main>
      <Footer />
    </div>
  );
}

function FeatureCard({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="border-border/60 bg-card flex flex-col gap-2 rounded-lg border p-6">
      <h3 className="text-lg font-semibold">{title}</h3>
      <p className="text-muted-foreground text-sm leading-relaxed">
        {description}
      </p>
    </div>
  );
}

function WorkflowCard({
  label,
  description,
  path,
  icon: Icon,
}: {
  label: string;
  description: string;
  path: string;
  icon: LucideIcon;
}) {
  return (
    <Link
      href={path}
      className="border-border/60 bg-card hover:border-primary/50 hover:bg-accent/50 flex flex-col gap-3 rounded-lg border p-6 transition-colors"
    >
      <Icon className="text-primary size-6" />
      <h3 className="text-lg font-semibold">{label}</h3>
      <p className="text-muted-foreground text-sm leading-relaxed">
        {description}
      </p>
    </Link>
  );
}
