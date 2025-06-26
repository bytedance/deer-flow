source /mnt/afs/yaotiankuo/agents/deer-main-dev/.venv/bin/activate
# uv run uv run main.py  --query "使用analyzer中的docparse工具看文件中张国战的所有加班时长, plan只需要一个step" --file /mnt/afs/yaotiankuo/agents/deer-dev/tests/加班清单.xlsx
# uv run uv run main.py  --query "看文件中张国战的所有加班时长, plan只需要一个step" --file /mnt/afs/yaotiankuo/agents/deer-dev/tests/加班清单.xlsx
# uv run main.py  --query "看文件中张国战的所有加班时长, 使用analyzer调用mcp服务查看,不使用coder" --file /mnt/afs/yaotiankuo/agents/deer-dev/tests/加班清单.xlsx
# uv run main.py  --query 分析目前agent的最新研究，给一个详细的报告
# uv run main.py  --query "图中画着什么东西" --file /mnt/afs/yaotiankuo/agents/deer-dev/tests/ts.png
# uv run main.py  --query "看看他是哪个学校毕业的" --file /mnt/afs/yaotiankuo/agents/deer-main-dev/tests/test_cases/cv.pdf
# uv run main.py  --query "从图中能获取哪些现象和推论？" --file /mnt/afs/yaotiankuo/agents/deer-dev/tests/report.jpg

# uv run main.py  --query "有哪些同学严重偏科, 不使用coder和search，只使用doc_parse" --file /mnt/afs/yaotiankuo/agents/deer-dev/tests/成绩单.xlsx
# uv run main.py  --query " 图中中国玩具的的线上销售渠道有哪些？" --file /mnt/afs/yaotiankuo/agents/deer-dev/tests/sell.jpg

# uv run main.py  --query "Q1: 这些材料体现了什么交通事故，责任如何认定？ Q2: 涉及事故的白色小汽车在哪些位置发生明显损坏，如果维修的话需要多少费用？请结合图片和必要的搜索材料回答该问题" --file /mnt/afs/yaotiankuo/agents/deer-dev/tests/multi_images/car1.jpg /mnt/afs/yaotiankuo/agents/deer-dev/tests/multi_images/car2.jpg /mnt/afs/yaotiankuo/agents/deer-dev/tests/multi_images/car3.jpg

# uv run main.py  --query "微博评论中统计积极/消极占比，并尝试解读其原因, 不使用coder" --file /mnt/afs/yaotiankuo/agents/deer-main-dev/tests/test_cases/multi_files

# uv run main.py  --query "这些是商业医疗保险理赔材料，请判断是否合规合理" --file /mnt/afs/yaotiankuo/agents/deer-main-dev/tests/test_cases/rotate_img

# uv run main.py  --query "将第二个图转正，整理成md输出" --file /mnt/afs/yaotiankuo/agents/deer-main-dev/tests/test_cases/rotate_img


# uv run main.py  --query "搜索一下 attention block的结构图，再帮我讲解一下"

# uv run main.py  --query "搜索一下唐人街探案1900 男主角两年前最热门的电影里的海报传的是什么衣服"


# uv run main.py  --query "广东考生，之前模拟考分数大概在 590 到 610 分之间，性别男，物理方向，孩子挺喜欢计算机编程的，但我们家庭就在广东二线城市，条件比较普通，希望他未来毕业后能找到稳定、待遇比较好的国企工作。孩子一直没出过省，比较想去北上广深这种大城市上学，并想出国交流学习，如果未来学校能有这方面的资源和支持就更好了。请问这种情况能报什么学校专业，以及这些专业的就业前景和薪资空间怎么样?"

uv run main.py  --query 写个财经小作文,随机按你喜好写别反问我
# uv run main.py  --query "分析历年上海考生的北大的分数线, 别反问我"