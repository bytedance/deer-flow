import { Activity, BotIcon, FileText, MessageSquare, Wrench } from "@/components/ui/icons";
import Link from "next/link";

import { Footer } from "@/components/landing/footer";
import { Header } from "@/components/landing/header";
import { Button } from "@/components/ui/button";
import { FlickeringGrid } from "@/components/ui/flickering-grid";
import { cn } from "@/lib/utils";

export default function LandingPage() {
  return (
    <div className="bg-background text-foreground relative min-h-screen w-full">
      <div className="noise-overlay" />
      <Header />
      <main
        id="main-content"
        className="container-md mx-auto flex w-full flex-col px-4 pt-32 pb-16 md:px-8"
      >
        <section className="flex flex-col gap-6 py-16 md:flex-row md:items-center md:text-left text-center">
          <div className="flex-1">
            <h1 className="text-4xl font-bold tracking-tight md:text-6xl">
              EHM AI 工作台
            </h1>
            <p className="text-muted-foreground mt-4 max-w-xl text-lg md:text-xl">
              工业设备智能诊断与监测平台。
              <br />
              面向石油石化行业，以 AI 驱动实时监测、故障诊断与运行报告。
            </p>
            <div className="flex gap-3 mt-6 md:justify-start justify-center">
              <Link href="/workspace">
                <Button size="lg">
                  <BotIcon className="mr-2 size-4" />
                  进入工作台
                </Button>
              </Link>
            </div>
          </div>
          <div className="hidden md:flex flex-1 items-center justify-center relative">
            <div className="absolute inset-0 overflow-hidden rounded-xl">
              <FlickeringGrid
                squareSize={4}
                gridGap={6}
                flickerChance={0.15}
                color="rgb(37, 99, 235)"
                maxOpacity={0.15}
              />
            </div>
            <div className="relative z-10 flex flex-col items-center gap-3">
              <div className="text-[120px] leading-none font-bold text-primary/10 select-none">
                ⚙
              </div>
              <p className="text-muted-foreground/40 text-xs tracking-widest uppercase">
                Equipment Health Management
              </p>
            </div>
          </div>
        </section>

        <section className="flex flex-col gap-4 py-16">
          <FeatureCard
            icon={<Activity className="size-5" />}
            title="实时监测"
            description="装置运行状态、关键测点数据随时查询。"
            large
          />
          <FeatureCard
            icon={<Wrench className="size-5" />}
            title="智能诊断"
            description="基于振动频谱、轴心轨迹、趋势特征的故障识别与根因分析。"
            large
          />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <FeatureCard
              icon={<FileText className="size-4" />}
              title="运行报告"
              description="日报、周报、月报由 AI 自动生成，统一 Markdown 文档可导出。"
            />
            <FeatureCard
              icon={<MessageSquare className="size-4" />}
              title="对话操作"
              description="自然语言描述设备问题，系统调用专业技能完成分析与处置建议。"
            />
          </div>
        </section>
      </main>
      <Footer />
    </div>
  );
}

function FeatureCard({
  title,
  description,
  icon,
  large = false,
}: {
  title: string;
  description: string;
  icon?: React.ReactNode;
  large?: boolean;
}) {
  return (
    <div
      className={cn(
        "group bg-muted/30 hover:bg-muted/60 motion-safe:transition-all motion-safe:duration-200 flex flex-col gap-3 rounded-xl p-6",
        large && "md:p-8",
      )}
    >
      {icon && (
        <div className="text-primary/60 group-hover:text-primary/80 transition-colors">
          {icon}
        </div>
      )}
      <h3 className={cn("font-semibold", large ? "text-xl" : "text-lg")}>
        {title}
      </h3>
      <p className="text-muted-foreground text-sm leading-relaxed">
        {description}
      </p>
    </div>
  );
}
