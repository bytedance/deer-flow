"""第 3 天：415．字符串相加。

给定表示非负整数的字符串 num1 和 num2，返回它们的和（字符串）。
不能直接把整个输入字符串转换成整数，也不能使用大整数库。
输入仅含数字，没有前导零（"0" 本身除外），长度为 1 至 10000。

先口述思路，再实现下面的方法。
运行：python learning/interview/day03_add_strings.py
"""


class Solution:
    def addStrings(self, num1: str, num2: str) -> str:
        i = len(num1) - 1
        j = len(num2) - 1
        carry = 0
        result = []
        while (i >= 0 or j >= 0 or carry != 0):
            x = int(num1[i]) if i >= 0 else 0
            y = int(num2[j]) if j >= 0 else 0
            total = x + y + carry
            now = str(total % 10)
            carry = total // 10
            result.append(now)
            i -= 1
            j -= 1
        result.reverse()
        text = "".join(result)
        return text
        


if __name__ == "__main__":
    result = Solution().addStrings("456", "77")
    print(result)  # 期望："533"
