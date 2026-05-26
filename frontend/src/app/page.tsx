import Link from "next/link";

import { Footer } from "@/components/landing/footer";
import { Header } from "@/components/landing/header";
import { Button } from "@/components/ui/button";

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
          <Link href="/workspace">
            <Button size="lg" className="mt-4">
              进入工作台
            </Button>
          </Link>
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
