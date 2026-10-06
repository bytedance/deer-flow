/**
 * tab 行折叠边界（spec 2026-09-28-kb-tabs-overflow §2 D1 乙）：
 * 未滚动态下"完整放得下"的前缀留平铺侧，其余进下拉——边界只随宽度变，
 * 滚动永不改下拉内容。itemEnds[i] = 第 i 个 trigger 的
 * offsetLeft + offsetWidth（与 D1 判定同口径，天然含 gap/内边距）。
 */
export function computeFoldCount(
  containerWidth: number,
  itemEnds: readonly number[],
  maskWidth: number,
): number {
  const overflow = itemEnds.some((end) => end > containerWidth);
  const effective = overflow ? containerWidth - maskWidth : containerWidth;
  let count = 0;
  for (const end of itemEnds) {
    if (end > effective) {
      break;
    }
    count += 1;
  }
  return count;
}
