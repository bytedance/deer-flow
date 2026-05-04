"use client";

import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useI18n } from "@/core/i18n/hooks";

interface CostChartProps {
  data: { date: string; cost: number }[];
}

export function CostChart({ data }: CostChartProps) {
  const { t } = useI18n();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium">{t.admin.costTrend}</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <AreaChart data={data}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
            <XAxis dataKey="date" className="text-xs" />
            <YAxis className="text-xs" />
            <Tooltip />
            <Area
              type="monotone"
              dataKey="cost"
              stroke="hsl(var(--primary))"
              fill="hsl(var(--primary)/.2)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
