// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";


import { Button } from "~/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "~/components/ui/card";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";
import { useAuth } from "~/core/auth/context";
import { AdminWrapper } from "~/core/auth/wrapper";

export default function AdminPage() {
  const { user } = useAuth();
  const t = useTranslations("admin");
  
  const [config, setConfig] = useState({
    tavilyApiKey: "",
    braveSearchApiKey: "",
    volcengineTtsAppId: "",
    ragflowApiKey: "",
  });

  // In a real implementation, you would fetch the current configuration from the backend
  useEffect(() => {
    // Mock loading of configuration
    const mockConfig = {
      tavilyApiKey: "tavily_****************",
      braveSearchApiKey: "brave_****************",
      volcengineTtsAppId: "volc_****************",
      ragflowApiKey: "ragflow_****************",
    };
    setConfig(mockConfig);
  }, []);

  const handleSave = () => {
    // In a real implementation, you would save the configuration to the backend
    alert(t("configSaved"));
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
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="tavilyApiKey">{t("tavilyApiKey")}</Label>
                <Input
                  id="tavilyApiKey"
                  type="password"
                  value={config.tavilyApiKey}
                  onChange={(e) => setConfig({ ...config, tavilyApiKey: e.target.value })}
                />
              </div>
              
              <div className="space-y-2">
                <Label htmlFor="braveSearchApiKey">{t("braveSearchApiKey")}</Label>
                <Input
                  id="braveSearchApiKey"
                  type="password"
                  value={config.braveSearchApiKey}
                  onChange={(e) => setConfig({ ...config, braveSearchApiKey: e.target.value })}
                />
              </div>
              
              <div className="space-y-2">
                <Label htmlFor="volcengineTtsAppId">{t("volcengineTtsAppId")}</Label>
                <Input
                  id="volcengineTtsAppId"
                  type="password"
                  value={config.volcengineTtsAppId}
                  onChange={(e) => setConfig({ ...config, volcengineTtsAppId: e.target.value })}
                />
              </div>
              
              <div className="space-y-2">
                <Label htmlFor="ragflowApiKey">{t("ragflowApiKey")}</Label>
                <Input
                  id="ragflowApiKey"
                  type="password"
                  value={config.ragflowApiKey}
                  onChange={(e) => setConfig({ ...config, ragflowApiKey: e.target.value })}
                />
              </div>
            </div>
            
            <div className="flex justify-end">
              <Button onClick={handleSave}>{t("saveConfiguration")}</Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </AdminWrapper>
  );
}