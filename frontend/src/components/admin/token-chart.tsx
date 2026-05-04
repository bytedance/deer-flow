"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useI18n } from "@/core/i18n/hooks";

interface TokenChartProps {
  data: { date: string; tokens: number }[];
}

export function TokenChart({ data }: TokenChartProps) {
  const { t } = useI18n();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium">{t.admin.tokenUsage}</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
            <XAxis dataKey="date" className="text-xs" />
            <YAxis className="text-xs" />
            <Tooltip />
            <Bar dataKey="tokens" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
