"""D07：56．合并区间。

每个区间 [start, end] 包含两个端点；输入不保证有序。
合并所有重叠区间，返回覆盖原范围且互不重叠的区间列表。
先手算并讨论思路，再由学习者实现；当前仅为练习骨架。

运行：python learning/interview/day07_merge_intervals.py
"""


class Solution:
    def merge(self, intervals: list[list[int]]) -> list[list[int]]:
        """输入至少有一个区间，每个区间满足 start <= end。"""
        # TODO：讨论思路后自行实现。
        intervals.sort(key=lambda item: item[0])
        results = []
        for lists in intervals:
            if results == []:
                results.append(lists)
            else:
                if results[-1][1] >= lists[0]:
                    results[-1] = [results[-1][0],max(results[-1][1],lists[1])]
                else:
                    results.append(lists)
        return results
if __name__ == "__main__":
    intervals = [[8, 10], [1, 4], [3, 7], [10, 12]]
    result = Solution().merge(intervals)
    print(result)
