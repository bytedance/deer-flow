/**
 * Allocate unique identifiers without interpreting existing names or requiring crypto.
 * The input is consumed once; each candidate is tested at most once per allocator.
 * @param {Iterable<string>} existing
 * @param {string} prefix
 * @param {number} start
 */
export function createUniqueIdAllocator(existing, prefix = "", start = 0) {
  const used = new Set(existing);
  let next = start;
  return () => {
    let id;
    do {
      id = `${prefix}${next++}`;
    } while (used.has(id));
    used.add(id);
    return id;
  };
}
