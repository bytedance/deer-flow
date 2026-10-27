"""第 1 天：两数之和。

返回和为 target 的两个元素的下标，不能重复使用同一个元素。
题目保证恰有一组答案，返回下标的顺序不限。

练习顺序：先实现最直接的解法，再考虑如何利用字典减少查找。
在仓库根目录运行：python learning/interview/day01_two_sum.py
"""


class Solution:
    def twoSum(self, nums: list[int], target: int) -> list[int]:
        seen = {}

        for i, num in enumerate(nums):
            need = target - num

            if need in seen:
                return [seen[need], i]

            seen[num] = i