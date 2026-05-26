"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Store } from "lucide-react";

import {
  useArchiveReportTemplate,
  usePublishReportTemplate,
  useReportTemplate,
  useReportTemplateVersions,
  useReportTemplateVersion,
  useUpdateReportTemplate,
  useValidateReportTemplate,
} from "@/core/report-templates";
import { useMarketplaceListing } from "@/core/marketplace/hooks";

interface Props {
  templateId: string;
}

export function ReportTemplateDetailPage({ templateId }: Props) {
  const { detail, isLoading, error } = useReportTemplate(templateId);
  const { versions } = useReportTemplateVersions(templateId);
  const template = detail?.template ?? null;

  const marketplaceSource = template?.marketplace_source;
  const { listing: upstreamListing } = useMarketplaceListing(
    marketplaceSource?.listing_id ?? "",
    { enabled: !!marketplaceSource },
  );

  const [selectedVersion, setSelectedVersion] = useState<number>(0);
  const { snapshot } = useReportTemplateVersion(
    templateId,
    selectedVersion >= 0 ? selectedVersion : 0,
  );

  const [editedYaml, setEditedYaml] = useState<string>("");
  const [editedJson, setEditedJson] = useState<string>("");
  const [parseError, setParseError] = useState<string | null>(null);

  // Sync editor when snapshot loads.
  useEffect(() => {
    if (!snapshot) return;
    setEditedYaml(snapshot.dsl_yaml);
    setEditedJson(JSON.stringify(snapshot.dsl, null, 2));
    setParseError(null);
  }, [snapshot]);

  const update = useUpdateReportTemplate(templateId);
  const publish = usePublishReportTemplate(templateId);
  const validate = useValidateReportTemplate(templateId);
  const archive = useArchiveReportTemplate(templateId);

  const isPublished = template?.status === "published";
  const canEdit = template && !isPublished && template.visibility !== "builtin";

  function parseDsl(): Record<string, unknown> | null {
    try {
      const parsed = JSON.parse(editedJson) as Record<string, unknown>;
      setParseError(null);
      return parsed;
    } catch (e) {
      setParseError((e as Error).message);
      return null;
    }
  }

  async function handleValidate() {
    const dsl = parseDsl();
    if (!dsl) return;
    const result = await validate.mutateAsync(dsl);
    if (result.valid) {
      toast.success(
        result.warnings.length > 0
          ? `校验通过（${result.warnings.length} 个警告）`
          : "校验通过",
      );
    } else {
      toast.error(`校验失败：${result.errors.length} 个错误`);
    }
  }

  async function handleSave() {
    if (!template || !canEdit) return;
    const dsl = parseDsl();
    if (!dsl) return;
    try {
      await update.mutateAsync({
        dsl,
        dsl_yaml: editedYaml,
        expected_etag: template.etag,
      });
      toast.success("草稿已保存");
    } catch (e) {
      toast.error(`保存失败：${(e as Error).message}`);
    }
  }

  async function handlePublish() {
    if (!template || !canEdit) return;
    try {
      await publish.mutateAsync({
        expected_current_version: template.current_version,
        changelog: "",
      });
      toast.success("已发布新版本");
    } catch (e) {
      toast.error(`发布失败：${(e as Error).message}`);
    }
  }

  async function handleArchive() {
    if (!template) return;
    try {
      await archive.mutateAsync(template.etag);
      toast.success("模板已归档");
    } catch (e) {
      toast.error(`归档失败：${(e as Error).message}`);
    }
  }

  if (isLoading) {
    return <div className="p-6 text-sm text-muted-foreground">加载中…</div>;
  }
  if (error || !template) {
    return (
      <div className="p-6">
        <Link href="/workspace/report-templates" className="text-sm underline">
          ← 返回列表
        </Link>
        <div className="mt-4 rounded border border-destructive bg-destructive/10 p-3 text-sm">
          {error ? String(error) : "模板不存在"}
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-4 p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link
            href="/workspace/report-templates"
            className="text-muted-foreground text-xs underline-offset-2 hover:underline"
          >
            ← 报告模板
          </Link>
          <h1 className="mt-1 text-2xl font-semibold">
            {template.display_name}
          </h1>
          <div className="text-muted-foreground mt-1 text-xs">
            <code className="font-mono">{template.name}</code> ·{" "}
            <span className="capitalize">{template.visibility}</span> · v
            {template.current_version} · {template.status}
          </div>
          {marketplaceSource && (
            <div className="mt-1.5 flex items-center gap-2">
              <Link
                href={`/workspace/template-marketplace/${marketplaceSource.listing_id}`}
                className="inline-flex items-center gap-1 rounded-full border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 text-[10px] font-medium text-blue-600 hover:bg-blue-500/20"
              >
                <Store className="h-3 w-3" />
                Installed from marketplace
              </Link>
              {upstreamListing &&
                upstreamListing.template_version >
                  marketplaceSource.source_version && (
                  <span className="inline-flex items-center rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-600">
                    Update available (v{upstreamListing.template_version})
                  </span>
                )}
            </div>
          )}
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            className="rounded border px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50"
            onClick={handleValidate}
            disabled={validate.isPending}
          >
            校验 DSL
          </button>
          <button
            type="button"
            className="rounded border px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50"
            onClick={handleSave}
            disabled={!canEdit || update.isPending}
          >
            保存草稿
          </button>
          <button
            type="button"
            className="rounded bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            onClick={handlePublish}
            disabled={!canEdit || publish.isPending}
          >
            {publish.isPending ? "发布中…" : "发布新版本"}
          </button>
          <button
            type="button"
            className="rounded border px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent"
            onClick={handleArchive}
          >
            归档
          </button>
        </div>
      </header>

      <div className="grid flex-1 grid-cols-[200px_1fr] gap-4 overflow-hidden">
        <aside className="overflow-y-auto rounded border bg-card p-3">
          <h2 className="mb-2 text-sm font-medium">版本</h2>
          <ul className="space-y-1 text-sm">
            <li>
              <button
                type="button"
                className={`w-full rounded px-2 py-1 text-left ${selectedVersion === 0 ? "bg-accent font-medium" : "hover:bg-accent"}`}
                onClick={() => setSelectedVersion(0)}
              >
                v0 工作草稿
              </button>
            </li>
            {versions.map((v) => (
              <li key={v}>
                <button
                  type="button"
                  className={`w-full rounded px-2 py-1 text-left ${selectedVersion === v ? "bg-accent font-medium" : "hover:bg-accent"}`}
                  onClick={() => setSelectedVersion(v)}
                >
                  v{v}
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <main className="flex flex-col gap-3 overflow-hidden rounded border bg-card p-3">
          {parseError && (
            <div className="rounded border border-destructive bg-destructive/10 p-2 text-xs">
              JSON 解析失败：{parseError}
            </div>
          )}
          {!canEdit && (
            <div className="rounded border border-amber-500/30 bg-amber-500/10 p-2 text-xs">
              {isPublished
                ? "已发布版本不可原地编辑——请通过 fork 创建新草稿。"
                : "Builtin 模板只读。"}
            </div>
          )}
          <label className="text-xs font-medium text-muted-foreground">
            DSL (JSON)
          </label>
          <textarea
            className="min-h-[160px] flex-1 rounded border bg-background p-3 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-ring"
            value={editedJson}
            onChange={(e) => setEditedJson(e.target.value)}
            readOnly={!canEdit}
            spellCheck={false}
          />
          <label className="text-xs font-medium text-muted-foreground">
            DSL YAML (备注/注释保留)
          </label>
          <textarea
            className="min-h-[120px] flex-1 rounded border bg-background p-3 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-ring"
            value={editedYaml}
            onChange={(e) => setEditedYaml(e.target.value)}
            readOnly={!canEdit}
            spellCheck={false}
          />
        </main>
      </div>
    </div>
  );
}
