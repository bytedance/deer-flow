// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";


import { Button } from "~/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "~/components/ui/card";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";
import { useAuth } from "~/core/auth/context";
import { AdminWrapper } from "~/core/auth/wrapper";
import { fetchAdminConfig, type AdminConfig, updateAdminConfig } from "~/core/api/admin";

export default function AdminPage() {
  const { user } = useAuth();
  const t = useTranslations("admin");
  const [config, setConfig] = useState<AdminConfig>({
    tavilyApiKey: "",
    braveSearchApiKey: "",
    volcengineTtsAppId: "",
    ragflowApiKey: "",
  });
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadConfig = useCallback(async () => {
    if (!user) return;

    setIsLoading(true);
    setError(null);
    try {
      const settings = await fetchAdminConfig();
      setConfig(settings);
    } catch (err) {
      console.error("Failed to fetch admin config:", err);
      setError("Failed to load configuration.");
    } finally {
      setIsLoading(false);
    }
  }, [user]);

  useEffect(() => {
    void loadConfig();
  }, [loadConfig]);

  const handleSave = async () => {
    setIsSaving(true);
    setError(null);
    try {
      await updateAdminConfig(config);
      toast.success(t("configSaved"));
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to save configuration.";
      setError(message);
      toast.error(message);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <AdminWrapper>
      <div className="container py-8">
        <Card>
          <CardHeader>
            <CardTitle>{t("systemConfiguration")}</CardTitle>
            <CardDescription>
              {t("systemConfigurationDescription")} {user?.name}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="flex flex-wrap items-center gap-2">
              {error && (
                <div className="text-sm text-red-500">
                  {error}
                </div>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={loadConfig}
                disabled={isLoading || isSaving}
                className="ml-auto"
              >
                <RefreshCw className="mr-2 h-4 w-4" />
                {t("refresh", { defaultMessage: "Refresh" })}
              </Button>
            </div>

            {isLoading ? (
              <div className="flex min-h-[200px] items-center justify-center text-muted-foreground">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                {t("loading", { defaultMessage: "Loading configuration..." })}
              </div>
            ) : (
              <div className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="tavilyApiKey">{t("tavilyApiKey")}</Label>
                  <Input
                    id="tavilyApiKey"
                    type="password"
                    value={config.tavilyApiKey}
                    onChange={(e) => setConfig({ ...config, tavilyApiKey: e.target.value })}
                    disabled={isSaving}
                  />
                </div>
                
                <div className="space-y-2">
                  <Label htmlFor="braveSearchApiKey">{t("braveSearchApiKey")}</Label>
                  <Input
                    id="braveSearchApiKey"
                    type="password"
                    value={config.braveSearchApiKey}
                    onChange={(e) => setConfig({ ...config, braveSearchApiKey: e.target.value })}
                    disabled={isSaving}
                  />
                </div>
                
                <div className="space-y-2">
                  <Label htmlFor="volcengineTtsAppId">{t("volcengineTtsAppId")}</Label>
                  <Input
                    id="volcengineTtsAppId"
                    type="password"
                    value={config.volcengineTtsAppId}
                    onChange={(e) => setConfig({ ...config, volcengineTtsAppId: e.target.value })}
                    disabled={isSaving}
                  />
                </div>
                
                <div className="space-y-2">
                  <Label htmlFor="ragflowApiKey">{t("ragflowApiKey")}</Label>
                  <Input
                    id="ragflowApiKey"
                    type="password"
                    value={config.ragflowApiKey}
                    onChange={(e) => setConfig({ ...config, ragflowApiKey: e.target.value })}
                    disabled={isSaving}
                  />
                </div>
              </div>
            )}
            
            <div className="flex justify-end">
              <Button onClick={handleSave} disabled={isSaving || isLoading}>
                {isSaving ? t("saving", { defaultMessage: "Saving..." }) : t("saveConfiguration")}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </AdminWrapper>
  );
}