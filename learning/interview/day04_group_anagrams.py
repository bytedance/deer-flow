"""第 4 天：49．字母异位词分组。

将字符串列表中互为字母异位词的字符串放入同一组，返回所有组。
组与组之间、组内字符串之间的顺序均不限；保留原字符串及重复项。
输入只含小写英文字母，允许空字符串。

先讨论字典的分组键，再自行实现下面的方法。
运行：python learning/interview/day04_group_anagrams.py
"""


class Solution:
    def groupAnagrams(self, strs: list[str]) -> list[list[str]]:
        """返回字母异位词的各个分组。"""
        # TODO：确定字典的 key 和 value 分别存什么，再实现分组。
        dic = {}
        for i,char in enumerate(strs):
            counts = [0]*26
            for i,ch in enumerate(char):
                index = ord(ch) - ord("a")
                counts[index] += 1
            tu = tuple(counts)
            if tu not in dic:
                dic[tu] = [char]
            else:
                dic[tu].append(char)
        return list(dic.values())
            


if __name__ == "__main__":
    result = Solution().groupAnagrams(["eat", "tea", "tan", "ate", "nat", "bat"])
    print(result)
    # 应有三组：eat/tea/ate、tan/nat、bat；顺序不限。
