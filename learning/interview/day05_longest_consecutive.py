"""第 5 天：128．最长连续序列。

给定无序整数列表，返回最长连续整数序列的长度。
连续指相邻数值相差 1，不要求它们在原列表中相邻；重复值不延长序列。
目标时间复杂度 O(n)。先讨论思路，再自行实现。

运行：python learning/interview/day05_longest_consecutive.py
"""


class Solution:
    def longestConsecutive(self, nums: list[int]) -> int:
        """返回最长连续整数序列的长度，空列表返回 0。"""
        # 已讨论：用集合快速查询，只从前一个数字不存在的位置开始计数。
        # TODO：遍历去重后的集合，统计各段长度，返回其中的最大值。
        num = set(nums)
        result = 0
        cur = 0
        for x in num:
            if x-1 not in num:
                cur = 1 
                while x + 1 in num:
                    cur += 1
                    x += 1
                result = max(result,cur)
        return result
if __name__ == "__main__":
    nums = [100, 4, 200, 1, 3, 2]
    result = Solution().longestConsecutive(nums)
    print(result)  # 完成实现后，此例应输出 4。
