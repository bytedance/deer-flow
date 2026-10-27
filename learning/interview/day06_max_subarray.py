"""D06：53．最大子数组和。

给定非空整数列表，返回一个非空、位置连续的子数组的最大元素和。
不能排序或跳着选元素；返回的是和，不是子数组长度。
先复习旧题并讨论思路，再由学习者实现。

运行：python learning/interview/day06_max_subarray.py
"""


class Solution:
    def maxSubArray(self, nums: list[int]) -> int:
        """nums 至少有一个元素，可以含负数、零或正数。"""
        # TODO：讨论思路后自行实现，先不复制完整解法。
        current = 0
        best = nums[0]
        for i,num in enumerate(nums):
            current += num
            best = max(best,current)
            if current <= 0:
                current = 0
        return best

if __name__ == "__main__":
    nums = [-2, 1, -3, 4, -1, 2, 1, -5, 4]
    result = Solution().maxSubArray(nums)
    print(result)  # 完成实现后，此例应输出 6。
