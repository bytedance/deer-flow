"""D08：560．和为 K 的子数组。

给定整数数组 nums 和整数 k，返回元素和等于 k 的连续非空子数组数量。
数组元素可以是正数、0或负数，不允许重排数组。
先手算并讨论思路，再由学习者实现。

运行：python learning/interview/day08_subarray_sum_equals_k.py
"""


class Solution:
    def subarraySum(self, nums: list[int], k: int) -> int:
        """返回满足条件的子数组数量；输入数组至少有一个元素。"""
        # TODO：完成复习、题意和思路讨论后自行实现。
        raise NotImplementedError("请先讨论思路，再填写算法")


if __name__ == "__main__":
    nums = [1, 1, 1]
    k = 2
    result = Solution().subarraySum(nums, k)
    print(result)
