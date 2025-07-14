import { useMemo } from "react";
import { useStore, useToolCalls } from "~/core/store";
import { Tooltip } from "./tooltip";
import { WarningFilled } from "@ant-design/icons";
import { useTranslations } from "next-intl";

export const Link = ({
  href,
  children,
  checkLinkCredibility = false,
}: {
  href: string | undefined;
  children: React.ReactNode;
  checkLinkCredibility: boolean;
}) => {
  const toolCalls = useToolCalls();
  const responding = useStore((state) => state.responding);

  const credibleLinks = useMemo(() => {
    const links = new Set<string>();
    if (!checkLinkCredibility) return links;

    (toolCalls || []).forEach((call) => {
      if (call && call.name === "web_search" && call.result) {
        try {
          const result = JSON.parse(call.result) as Array<{ url: string }>;
          if (Array.isArray(result)) {
            result.forEach((r) => {
              if (r && typeof r.url === 'string') {
                // encodeURI is used to handle the case where the link contains chinese or other special characters
                links.add(encodeURI(r.url));
                links.add(r.url);
              }
            });
          }
        } catch (error) {
          console.warn('Failed to parse web_search result:', error);
        }
      }
    });
    return links;
  }, [toolCalls]);

  const isCredible = useMemo(() => {
    return checkLinkCredibility && href && !responding
      ? credibleLinks.has(href)
      : true;
  }, [credibleLinks, href, responding, checkLinkCredibility]);

  const t = useTranslations("common");
  return (
    <span className="inline-flex items-center gap-1.5">
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
      {!isCredible && (
        <Tooltip title={t("linkNotReliable")} delayDuration={300}>
          <WarningFilled className="text-sx transition-colors hover:!text-yellow-500" />
        </Tooltip>
      )}
    </span>
  );
};
