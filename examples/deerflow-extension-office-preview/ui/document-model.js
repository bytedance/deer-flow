/** Resolve only package-local relationships, with the same POSIX path semantics as OOXML. */
export function resolvePartPath(base, target) {
  const segments = target.startsWith("/") ? [] : base.split("/").slice(0, -1);
  for (const part of target.split("/")) {
    if (part === "..") segments.pop();
    else if (part && part !== ".") segments.push(part);
  }
  return segments.join("/");
}

/** Reject amplified parser output before structured clone or DOM creation. */
export function checkModelBudget(value) {
  const seen = new Set(),
    stack = [value];
  let nodes = 0,
    bytes = 0;
  while (stack.length) {
    const item = stack.pop();
    if (typeof item === "string") bytes += item.length * 2;
    else if (item && typeof item === "object" && !seen.has(item)) {
      seen.add(item);
      if (++nodes > 100000) throw new Error("Office model node limit exceeded");
      if (item instanceof ArrayBuffer) bytes += item.byteLength;
      else if (ArrayBuffer.isView(item)) {
        if (!seen.has(item.buffer)) {
          seen.add(item.buffer);
          bytes += item.buffer.byteLength;
        }
      } else {
        if (Array.isArray(item) && item.length > 100000)
          throw new Error("Office model array limit exceeded");
        for (const [key, child] of Object.entries(item)) {
          bytes += key.length * 2;
          stack.push(child);
        }
      }
    }
    if (bytes > 32 * 1024 * 1024)
      throw new Error("Office model size limit exceeded");
  }
}

/** Transfer each resource once; do not clone validated image bytes back to the UI. */
export function transferBuffers(value) {
  const seen = new Set(),
    buffers = new Set(),
    stack = [value];
  while (stack.length) {
    const item = stack.pop();
    if (!item || typeof item !== "object" || seen.has(item)) continue;
    seen.add(item);
    if (item instanceof ArrayBuffer) buffers.add(item);
    else if (ArrayBuffer.isView(item)) buffers.add(item.buffer);
    else stack.push(...Object.values(item));
  }
  return [...buffers];
}
