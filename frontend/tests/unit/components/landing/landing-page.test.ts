import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    children,
    ...props
  }: React.PropsWithChildren<Record<string, unknown>>) =>
    React.createElement("a", props, children),
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    ...props
  }: React.PropsWithChildren<Record<string, unknown>>) =>
    React.createElement("button", props, children),
}));

vi.mock("@/components/landing/header", () => ({
  Header: () => React.createElement("header", null, "header"),
}));

vi.mock("@/components/landing/footer", () => ({
  Footer: () => React.createElement("footer", null, "footer"),
}));

import LandingPage from "@/app/page";

describe("LandingPage", () => {
  it("renders industrial positioning headline", () => {
    const html = renderToStaticMarkup(React.createElement(LandingPage));

    expect(html).toContain("EHM AI 工作台");
    expect(html).toContain("工业设备智能诊断与监测平台");
  });

  it("mentions target industry", () => {
    const html = renderToStaticMarkup(React.createElement(LandingPage));

    expect(html).toContain("石油石化");
  });

  it("renders industrial feature cards", () => {
    const html = renderToStaticMarkup(React.createElement(LandingPage));

    expect(html).toContain("实时监测");
    expect(html).toContain("智能诊断");
    expect(html).toContain("运行报告");
    expect(html).toContain("对话操作");
  });

  it("renders call-to-action button", () => {
    const html = renderToStaticMarkup(React.createElement(LandingPage));

    expect(html).toContain("进入工作台");
  });
});
