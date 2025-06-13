import argparse
import asyncio
import fvg.utils.prompts
import fvg.utils.tablelib
import importlib
import json
import os
import pandas as pd
import threading
import time


TEMPLATES = {
    'v1': fvg.utils.prompts.template_zh_v1,
}
SYS_MSGS = {
    'v1': fvg.utils.prompts.sys_msg_zh,
    'v2': fvg.utils.prompts.sys_msg_zh_v2,
    'v2_vis': fvg.utils.prompts.sys_msg_zh_v2_vis,
    'sys_msg_zh_yyb2': fvg.utils.prompts.sys_msg_zh_yyb2
}


class ExcelAgentRunner:
    def __init__(self, args):
        self.args = args
        self.template = TEMPLATES[args.template_version]
        self.sys_msg = SYS_MSGS[args.sys_version]
        self.message_dict = {}
        if os.path.exists(args.message_path):
            with open(args.message_path, 'r', encoding='utf-8') as f:
                self.message_dict = json.load(f)

    async def process_row(self, thread_local, config, index, row, sem):
        if not hasattr(thread_local, 'agent'):
            thread_local.agent = make_object_from_config(config['agent'])

        if not pd.isnull(row['answer']):
            print('Skip {}'.format(index))
            return index, row['answer'], None

        if config['dataset_type'] == '64':
            file = os.path.join(
                config['resource_path'], row['样张链接'].split('/')[-1])
            info2 = fvg.utils.tablelib.extract_workbook_summary3b(file)
            entry = {
                'path': file,
                'question': row['question'],
                'task_prompt': row['question'],
                'info2': info2
            }
            task = self.template.format_map(entry)
            sys_msg = self.sys_msg.format_map(entry)

        try:
            async with sem:
                print("Q {}: {}".format(index, task))
                response = await thread_local.agent.ainvoke(
                    {
                        "messages": [
                            {'role': 'system', 'content': sys_msg},
                            {'role': 'user', 'content': task}
                        ]
                    },
                    {
                        "configurable": {
                            "thread_id": hash("{}-{}".format(
                                threading.get_native_id(), index))
                        },
                        "recursion_limit": 50
                    }
                )

            answer = response["messages"][-1].text()
            messages = [i.text() for i in response["messages"]]
            print("R {}\n{}".format(index, answer))

        except Exception as e:
            answer = ""
            messages = str(e)
            print("R error {}\n{}".format(index, messages))
        return index, answer, messages

    async def run_parallel(self, config, output_path, message_path):
        sem = asyncio.Semaphore(config['thread_pool']["max_workers"])
        thread_local = threading.local()
        futures = [
            self.process_row(thread_local, config, i, row, sem)
            for i, row in self.df.iterrows()
        ]
        for future in asyncio.as_completed(futures):
            i, answer, messages = await future
            if answer is not None:
                self.df.loc[i, 'answer'] = answer
                self.message_dict[i] = messages
                self.df.to_excel(output_path, index=False)
                with open(message_path, 'w', encoding='utf-8') as f:
                    json.dump(
                        self.message_dict, f, indent=4, ensure_ascii=False)

    def run_sequential(self, config, output_path, message_path):
        sem = asyncio.Semaphore(1)
        for i, row in self.df.iterrows():
            i, answer, messages = asyncio.run(
                self.process_row(self, config, i, row, sem))
            if answer is not None:
                self.df.loc[i, 'answer'] = answer
                self.message_dict[i] = messages
                self.df.to_excel(output_path, index=False)
                with open(message_path, 'w', encoding='utf-8') as f:
                    json.dump(
                        self.message_dict, f, indent=4, ensure_ascii=False)

    def run(self, config, output_path, message_path):
        self.df = load_data_table(config)

        if "thread_pool" in config:
            asyncio.run(
                self.run_parallel(config, output_path, message_path))
        else:
            self.run_sequential(config, output_path, message_path)

        print("Done")


def create_parser():
    parser = argparse.ArgumentParser(
        description='The script to run the benchmark for the document agent.')
    parser.add_argument(
        '-c', '--config-path', type=str, required=True,
        help='The path to the config file.')
    parser.add_argument(
        '-o', '--output-path', type=str, required=True,
        help='The path to save the answers in .xlsx format.')
    parser.add_argument(
        '-m', '--message-path', type=str, required=True,
        help='The path to save the messages in JSON format.')
    parser.add_argument("--template-version", type=str, default="v1")
    parser.add_argument("--sys-version", type=str, default="v2")
    return parser


def make_object(module: str, class_name: str, args=None):
    _module = importlib.import_module(module, package=None)
    _class = getattr(_module, class_name)
    return _class() if args is None else _class(**args)


def make_object_from_config(config):
    if isinstance(config, list):
        return [make_object_from_config(i) for i in config]
    elif isinstance(config, dict):
        if "module" in config and "class_name" in config:
            if "args" in config:
                config["args"] = make_object_from_config(config["args"])

            return make_object(**config)
        else:
            return {
                k: make_object_from_config(v)
                for k, v in config.items()
            }
    else:
        return config


def load_data_table(config):
    if config['dataset_type'] == '64':
        index_table = make_object(**config['index_table'])
    else:
        raise Exception(
            'Unsupported dataset_type: {}'.format(config['dataset_type']))

    if 'answer' not in index_table.columns:
        index_table['answer'] = None

    return index_table


if __name__ == "__main__":
    parser = create_parser()
    args = parser.parse_args()

    with open(args.config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    runner = ExcelAgentRunner(args)
    t1 = time.time()
    runner.run(config, args.output_path, args.message_path)
    print("Elapsed time: {:.2f} s".format(time.time() - t1))
