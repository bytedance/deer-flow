import argparse
import concurrent.futures
import importlib
import json
import threading


system_prompt = """你是一个擅长打分的小助手。现在请你给AI模型的答案进行打分。我们会给你提供以下信息：
1. 问题
2. 参考答案
2. 需要打分的AI模型答案

打分标准：共两档，0分，1分。请根据问题和参考答案，对AI模型的答案进行判断：
1. 统计类题目：若AI模型的计算结果与参考答案基本一致（统计数据需更严格对应），则判定为1分；若计算结果与参考答案存在明显差异，判定为0分。
2. 知识问答与分析类题目：若AI模型答案能完整覆盖参考答案的核心要点，且表述逻辑与原意相符，判定为1分；若答案与参考答案存在显著偏差，核心要点缺失，则判定为0分。

注意：
1. 模型的答案可能包含其分析过程，但主要关注最终的结论。
2. 数据可能保留小数不一样，四舍五入后相同也算数据对。
3. 对于表格的对照，需要仔细理解题目后进行对比判断。
4. 只需关注答案逻辑，任何回答语言都能接受（中、英...）

输出仅包含如下格式的 JSON 字符串，不要包含任何非 JSON 内容: 
{{"score": [打分], "reason": "[解释你这样打分的原因]"}}
"""

user_prompt = """
问题:\n{question}
参考答案:\n{参考答案}
AI模型答案:\n{answer}
"""


def create_parser():
    parser = argparse.ArgumentParser(
        description='The script to count point for the document agent '
        'benchmark.')
    parser.add_argument(
        '-c', '--config-path', type=str, required=True,
        help='The path to the config file.')
    return parser


def make_object(module: str, class_name: str, args: dict = None):
    _module = importlib.import_module(module, package=None)
    _class = getattr(_module, class_name)
    return _class() if args is None else _class(**args)


def score(thread_local, config, row):
    if not hasattr(thread_local, 'chat_model'):
        thread_local.chat_model = make_object(
            **config['chat_model'])

    response = thread_local.chat_model.invoke([
        {
            'role': 'system',
            'content': system_prompt
        },
        {
            'role': 'user',
            'content': user_prompt.format_map(row)
        }
    ])
    return json.loads(response.content)


if __name__ == '__main__':
    parser = create_parser()
    args = parser.parse_args()

    with open(args.config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)['scoring']

    answer_table = make_object(**config['answer_table'])
    scores = []

    thread_local = threading.local()
    with concurrent.futures.ThreadPoolExecutor(
        **config['thread_pool']
    ) as executor:
        futures = {
            executor.submit(score, thread_local, config, row): i
            for i, row in answer_table.iterrows()
        }
        for future in concurrent.futures.as_completed(futures):
            i = futures[future]
            try:
                result = future.result()
                scores.append(result['score'])
                print(
                    'Line {}, score: {}, reason: {}'
                    .format(i, result['score'], result['reason']))
            except Exception as e:
                print('Line {}, error: {}'.format(i, str(e)))

    print('Done: {:.1f}'.format(sum(scores) / answer_table.shape[0] * 100))
