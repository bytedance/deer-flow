import {
  Children,
  Fragment,
  cloneElement,
  isValidElement,
  type HTMLAttributes,
  type ReactNode,
} from "react";
import type { StreamdownProps } from "streamdown";

type StreamdownNode = {
  tagName?: string;
  position?: {
    start?: { line?: number };
    end?: { line?: number };
  };
};

type StreamdownParagraphProps = HTMLAttributes<HTMLParagraphElement> & {
  node?: StreamdownNode;
};

const BLOCK_TAGS = new Set([
  "article",
  "aside",
  "blockquote",
  "dd",
  "div",
  "dl",
  "dt",
  "figure",
  "figcaption",
  "footer",
  "form",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "header",
  "hr",
  "iframe",
  "li",
  "main",
  "nav",
  "ol",
  "p",
  "pre",
  "section",
  "table",
  "tbody",
  "td",
  "tfoot",
  "th",
  "thead",
  "tr",
  "ul",
]);

const BLOCK_STREAMDOWN_VALUES = new Set([
  "blockquote",
  "code-block",
  "heading-1",
  "heading-2",
  "heading-3",
  "heading-4",
  "heading-5",
  "heading-6",
  "horizontal-rule",
  "ordered-list",
  "table",
  "table-body",
  "table-row",
  "table-wrapper",
  "unordered-list",
]);

function isOnlyImage(children: ReactNode) {
  const nonEmptyChildren = Children.toArray(children).filter(
    (child) => child !== "",
  );
  const [onlyChild] = nonEmptyChildren;

  return (
    nonEmptyChildren.length === 1 &&
    isValidElement<{ node?: StreamdownNode }>(onlyChild) &&
    onlyChild.props.node?.tagName === "img"
  );
}

function isMultilineCodeNode(node: StreamdownNode | undefined): boolean {
  if (node?.tagName !== "code" && node?.tagName !== "pre") {
    return false;
  }

  const startLine = node?.position?.start?.line;
  const endLine = node?.position?.end?.line;

  return (
    typeof startLine === "number" &&
    typeof endLine === "number" &&
    startLine !== endLine
  );
}

function isBlockElement(child: ReactNode): boolean {
  if (!isValidElement(child)) {
    return false;
  }

  if (typeof child.type === "string" && BLOCK_TAGS.has(child.type)) {
    return true;
  }

  const props = child.props as {
    children?: ReactNode;
    node?: StreamdownNode;
    "data-code-block-container"?: unknown;
    "data-streamdown"?: unknown;
  };

  if (
    props["data-code-block-container"] ||
    (typeof props["data-streamdown"] === "string" &&
      BLOCK_STREAMDOWN_VALUES.has(props["data-streamdown"])) ||
    (props.node?.tagName && BLOCK_TAGS.has(props.node.tagName)) ||
    isMultilineCodeNode(props.node)
  ) {
    return true;
  }

  return Children.toArray(props.children).some(isBlockElement);
}

function withKey(node: ReactNode, key: string) {
  if (!isValidElement(node)) {
    return <Fragment key={key}>{node}</Fragment>;
  }

  return node.key == null ? cloneElement(node, { key }) : node;
}

export function SafeParagraph({
  children,
  node: _node,
  ...props
}: StreamdownParagraphProps) {
  if (isOnlyImage(children)) {
    return <>{children}</>;
  }

  const childArray = Children.toArray(children).filter((child) => child !== "");

  if (!childArray.some(isBlockElement)) {
    return <p {...props}>{children}</p>;
  }

  const chunks: ReactNode[] = [];
  let inlineBuffer: ReactNode[] = [];

  const flushInlineBuffer = () => {
    if (inlineBuffer.length === 0) {
      return;
    }

    chunks.push(
      <p key={`inline-${chunks.length}`} {...props}>
        {inlineBuffer}
      </p>,
    );
    inlineBuffer = [];
  };

  childArray.forEach((child, index) => {
    if (isBlockElement(child)) {
      flushInlineBuffer();
      chunks.push(withKey(child, `block-${index}`));
      return;
    }

    inlineBuffer.push(child);
  });

  flushInlineBuffer();

  return <>{chunks}</>;
}

export function withSafeParagraph(
  components?: StreamdownProps["components"],
): StreamdownProps["components"] {
  return {
    ...components,
    p: SafeParagraph,
  };
}