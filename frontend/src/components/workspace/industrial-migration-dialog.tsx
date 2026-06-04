"use client";

import { Factory, Check, Loader2 } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useIndustrialMigration } from "@/core/industrial-migration";

export function IndustrialMigrationDialog() {
  const { showDialog, isProcessing, onAccept, onDecline } =
    useIndustrialMigration();

  return (
    <Dialog open={showDialog} onOpenChange={(open) => !open && onDecline()}>
      <DialogContent
        showCloseButton={false}
        className="sm:max-w-md"
        onInteractOutside={(e) => {
          if (isProcessing) e.preventDefault();
        }}
        onEscapeKeyDown={(e) => {
          if (isProcessing) e.preventDefault();
        }}
      >
        <DialogHeader>
          <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
            <Factory className="h-6 w-6 text-primary" />
          </div>
          <DialogTitle className="text-center">
            工业智能功能已就绪
          </DialogTitle>
          <DialogTitle className="text-center text-sm font-normal text-muted-foreground">
            Industrial Intelligence is Ready
          </DialogTitle>
        </DialogHeader>

        <DialogDescription asChild>
          <div className="space-y-4 py-2 text-sm">
            <p>
              工业智能已成为平台的核心能力。启用后，以下工业技能将自动激活：
            </p>
            <ul className="space-y-2 pl-1">
              {[
                { name: "设备振动诊断", desc: "Vibration Diagnosis" },
                { name: "设备监测分析", desc: "Monitoring Analysis" },
                { name: "趋势报告", desc: "Trend Report" },
                { name: "故障分析", desc: "Failure Analysis" },
                { name: "巡检总结", desc: "Inspection Summary" },
              ].map((skill) => (
                <li key={skill.name} className="flex items-start gap-2">
                  <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  <span>
                    <span className="font-medium">{skill.name}</span>
                    <span className="ml-1 text-muted-foreground text-xs">
                      {skill.desc}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
            <p className="text-muted-foreground">
              您可以随时在技能设置中调整配置。暂不启用不会影响现有功能。
            </p>
          </div>
        </DialogDescription>

        <DialogFooter className="flex-col gap-2 sm:flex-col">
          <Button
            onClick={onAccept}
            disabled={isProcessing}
            className="w-full"
          >
            {isProcessing ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Factory className="mr-2 h-4 w-4" />
            )}
            启用工业智能 / Enable Industrial Intelligence
          </Button>
          <Button
            variant="ghost"
            onClick={onDecline}
            disabled={isProcessing}
            className="w-full text-muted-foreground"
          >
            暂不启用 / Not Now
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
