"""第 2 天：242．有效的字母异位词。

判断能否仅通过重新排列 s 的字符得到 t，返回 bool。
基础题中 s 和 t 仅包含小写英文字母，长度均为 1 至 50000。

先口述思路，再实现下面的方法。
运行：python learning/interview/day02_valid_anagram.py
"""


class Solution:
    def isAnagram(self, s: str, t: str) -> bool:
        dict_s = {}
        dict_t = {}
        for i,cha in enumerate(s):
            if cha in dict_s:
                dict_s[cha] += 1
            else:
                dict_s[cha] = 1
        for i,cha in enumerate(t):
            if cha in dict_t:
                dict_t[cha] += 1
            else:
                dict_t[cha] = 1
        return dict_s == dict_t

if __name__ == "__main__":
    result = Solution().isAnagram("aab", "abb")
    print(result)  # 期望：True
