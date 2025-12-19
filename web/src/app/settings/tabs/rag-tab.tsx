// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { Database, FileText, Upload } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "~/components/ui/button";
import { resolveServiceURL } from "~/core/api/resolve-service-url";
import type { Resource } from "~/core/messages";
import { cn } from "~/lib/utils";

import type { Tab } from "./types";

export const RAGTab: Tab = () => {
  const t = useTranslations("settings.rag");
  const [resources, setResources] = useState<Resource[]>([]);
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchResources = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch(resolveServiceURL("rag/resources"), {
        method: "GET",
      });
      if (response.ok) {
        const data = await response.json();
        setResources(data.resources ?? []);
      }
    } catch (error) {
      console.error("Failed to fetch resources:", error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchResources();
  }, [fetchResources]);

  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    if (file.size === 0) {
      toast.error(t("emptyFile"));
      event.target.value = "";
      return;
    }

    setUploading(true);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch(resolveServiceURL("rag/upload"), {
        method: "POST",
        body: formData,
      });

      if (response.ok) {
        toast.success(t("uploadSuccess"));
        void fetchResources();
      } else {
        const error = await response.json();
        toast.error(error.detail ?? t("uploadFailed"));
      }
    } catch (error) {
      console.error("Upload error:", error);
      toast.error(t("uploadFailed"));
    } finally {
      setUploading(false);
      // Reset input value to allow uploading same file again
      event.target.value = "";
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <header>
        <div className="flex items-center justify-between gap-2">
          <h1 className="text-lg font-medium">{t("title")}</h1>
          <div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".md,.txt"
              className="sr-only"
              onChange={handleUpload}
              disabled={uploading}
              aria-label={t("upload")}
            />
            <Button
              disabled={uploading}
              onClick={() => fileInputRef.current?.click()}
            >
              <Upload className="mr-2 h-4 w-4" />
              {uploading ? t("uploading") : t("upload")}
            </Button>
          </div>
        </div>
        <div className={cn("text-muted-foreground text-sm")}>{t("description")}</div>
      </header>
      <main>
        {loading ? (
          <div className="flex items-center justify-center p-8 text-sm text-gray-500">
            {t("loading")}
          </div>
        ) : resources.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-8 text-center text-gray-500">
            <Database className="h-8 w-8 opacity-50" />
            <p>{t("noResources")}</p>
          </div>
        ) : (
          <ul className="flex flex-col gap-2">
            {resources.map((resource, index) => (
              <li
                key={resource.uri}
                className={cn("bg-card flex items-start gap-3 rounded-lg border p-3")}
              >
                <div className={cn("bg-primary/10 rounded p-2")}>
                  <FileText className="text-primary h-5 w-5" />
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="truncate font-medium">{resource.title}</h3>
                  <div className={cn("text-muted-foreground flex items-center gap-2 text-xs")}>
                    <span className="truncate max-w-[300px]" title={resource.uri}>
                      {resource.uri}
                    </span>
                    {resource.description && (
                      <>
                        <span>•</span>
                        <span className="truncate">{resource.description}</span>
                      </>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  );
};

RAGTab.icon = Database;
RAGTab.displayName = "Resources";
