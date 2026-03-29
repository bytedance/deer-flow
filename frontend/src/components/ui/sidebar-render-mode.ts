export type SidebarCollapsibleMode = "offcanvas" | "icon" | "none";

export function shouldRenderMobileSidebarSheet({
  isMobile,
  collapsible,
  state,
}: {
  isMobile: boolean;
  collapsible: SidebarCollapsibleMode;
  state: "expanded" | "collapsed";
}): boolean {
  return (
    isMobile &&
    !(
      collapsible === "icon" &&
      state === "collapsed"
    )
  );
}
