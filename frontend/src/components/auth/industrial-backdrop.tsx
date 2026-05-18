/**
 * IndustrialBackdrop — decorative SVG used as the left panel on auth pages.
 *
 * Composition: a low-saturation industrial blueprint of a process unit
 * (towers, exchangers, pipelines, gauges) layered over the workspace
 * background color, paired with a minimal product mark and a few engineering
 * data points. Intentionally static — no animation, in keeping with
 * ISA-101 §6.6 ("motion only on state change"). The watermark uses the
 * `--primary` token so it stays coherent across themes (light / dark /
 * industrial-light / industrial-dark).
 */
export function IndustrialBackdrop() {
  return (
    <div className="bg-card text-card-foreground relative hidden h-full overflow-hidden lg:block">
      <svg
        aria-hidden="true"
        className="text-primary/15 pointer-events-none absolute inset-0 h-full w-full"
        viewBox="0 0 800 1000"
        preserveAspectRatio="xMidYMid slice"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
      >
        {/* horizon grid */}
        <g strokeDasharray="2 6" strokeOpacity="0.4">
          <line x1="0" y1="200" x2="800" y2="200" />
          <line x1="0" y1="400" x2="800" y2="400" />
          <line x1="0" y1="600" x2="800" y2="600" />
          <line x1="0" y1="800" x2="800" y2="800" />
        </g>

        {/* distillation tower */}
        <g>
          <rect x="120" y="220" width="80" height="520" rx="6" />
          <line x1="120" y1="280" x2="200" y2="280" />
          <line x1="120" y1="340" x2="200" y2="340" />
          <line x1="120" y1="400" x2="200" y2="400" />
          <line x1="120" y1="460" x2="200" y2="460" />
          <line x1="120" y1="520" x2="200" y2="520" />
          <line x1="120" y1="580" x2="200" y2="580" />
          <line x1="120" y1="640" x2="200" y2="640" />
          <line x1="120" y1="700" x2="200" y2="700" />
          <path d="M 160 220 L 160 180 L 220 180" />
          <circle cx="220" cy="180" r="3" fill="currentColor" />
        </g>

        {/* heat exchanger */}
        <g transform="translate(310 540)">
          <rect x="0" y="0" width="220" height="80" rx="40" />
          <line x1="40" y1="0" x2="40" y2="80" />
          <line x1="180" y1="0" x2="180" y2="80" />
          <path d="M 110 0 L 110 -60 L 70 -60" />
          <circle cx="70" cy="-60" r="3" fill="currentColor" />
        </g>

        {/* secondary tower */}
        <g>
          <rect x="600" y="320" width="60" height="380" rx="4" />
          <line x1="600" y1="380" x2="660" y2="380" />
          <line x1="600" y1="440" x2="660" y2="440" />
          <line x1="600" y1="500" x2="660" y2="500" />
          <line x1="600" y1="560" x2="660" y2="560" />
          <line x1="600" y1="620" x2="660" y2="620" />
          <path d="M 630 320 L 630 280 L 700 280" />
          <circle cx="700" cy="280" r="3" fill="currentColor" />
        </g>

        {/* spherical tank */}
        <g transform="translate(380 760)">
          <circle cx="60" cy="60" r="60" />
          <line x1="60" y1="120" x2="60" y2="160" />
          <line x1="20" y1="160" x2="100" y2="160" />
          <line x1="30" y1="160" x2="30" y2="190" />
          <line x1="90" y1="160" x2="90" y2="190" />
        </g>

        {/* pipelines */}
        <g strokeOpacity="0.7">
          <path d="M 200 740 L 310 580" />
          <path d="M 530 580 L 600 580" />
          <path d="M 200 460 L 280 460 L 280 200 L 600 200 L 600 320" />
        </g>

        {/* gauge cluster */}
        <g transform="translate(50 50)">
          <circle cx="20" cy="20" r="18" />
          <path d="M 20 20 L 30 12" strokeWidth="1.5" />
          <line x1="20" y1="2" x2="20" y2="6" />
          <line x1="38" y1="20" x2="34" y2="20" />
        </g>
        <g transform="translate(700 880)">
          <circle cx="20" cy="20" r="18" />
          <path d="M 20 20 L 12 14" strokeWidth="1.5" />
        </g>
      </svg>

      {/* foreground content */}
      <div className="relative flex h-full flex-col justify-between p-10 xl:p-14">
        <div className="flex items-center gap-2">
          <span
            className="bg-primary inline-flex h-8 w-8 items-center justify-center rounded text-sm font-bold text-white"
            aria-hidden="true"
          >
            E
          </span>
          <span className="text-foreground text-base font-semibold tracking-tight">
            EHM AI 工作台
          </span>
        </div>

        <div className="flex flex-col gap-4">
          <div className="text-foreground text-3xl leading-tight font-semibold xl:text-4xl">
            为石油石化装置
            <br />
            提供 AI 设备健康洞察
          </div>
          <p className="text-muted-foreground max-w-md text-sm leading-relaxed">
            实时监测 · 智能诊断 · 智能日报 ·
            班次交接。在对话中完成设备运行分析与处置建议。
          </p>

          <dl className="mt-6 grid max-w-md grid-cols-3 gap-4 border-t pt-6">
            <BackdropStat label="覆盖装置" value="常减压" />
            <BackdropStat label="诊断维度" value="振动 / 温度 / 流量" />
            <BackdropStat label="报警等级" value="5 级" />
          </dl>
        </div>

        <div className="text-muted-foreground/80 flex items-center gap-2 text-xs">
          <span
            className="bg-status-running inline-block h-1.5 w-1.5 rounded-full"
            aria-hidden="true"
          />
          系统运行正常
          <span className="mx-2">·</span>
          沈阳因思科技
        </div>
      </div>
    </div>
  );
}

function BackdropStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <dt className="text-muted-foreground text-[10px] tracking-wider uppercase">
        {label}
      </dt>
      <dd
        className="text-foreground text-sm font-medium"
        style={{ fontVariantNumeric: "tabular-nums" }}
      >
        {value}
      </dd>
    </div>
  );
}
