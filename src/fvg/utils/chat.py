import argparse
import fvg.common
from fvg.messages.utils import convert_to_openai_messages
import json
import threading


class ChuckPrinter:
    def __init__(self):
        self.current_step = 0

    def update(self, message_chunk, metadata):
        if self.current_step != metadata['langgraph_step']:
            if self.current_step > 0:
                print()

            self.current_step = metadata['langgraph_step']
            print('{}:'.format(metadata['langgraph_node']), end='')
            if (
                metadata['langgraph_node'] == 'model' and
                'tags' in metadata and metadata['tags'] is not None
            ):
                for i in metadata['tags']:
                    print('{}:'.format(i), end='')

        if 'tool_calls' in message_chunk.additional_kwargs:
            for i in message_chunk.additional_kwargs['tool_calls']:
                if i['function']['name']:
                    print('\n->{}:'.format(i['function']['name']), end='')

                if i['function']['arguments']:
                    print(i['function']['arguments'], end='')

        elif message_chunk.content:
            print(message_chunk.content, end='', flush=True)


def create_parser():
    parser = argparse.ArgumentParser(
        description='The script to chat with the agent.')
    parser.add_argument(
        '-c', '--config-path', type=str, required=True,
        help='The path to the config file.')
    parser.add_argument(
        '-o', '--output-path', default=None, type=str,
        help='The path to the save the chat history (if given).')
    return parser


if __name__ == '__main__':
    parser = create_parser()
    args = parser.parse_args()

    with open(args.config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    agent = fvg.common.make_object_from_config(config['agent'])
    stream_config = {
        'configurable': {'thread_id': str(threading.get_native_id())},
        **config.get('stream_config', {})
    }
    while True:
        user_input = input('human: ')
        if user_input == 'q':
            break

        graph_output = agent.stream(
            {'messages': [{'role': 'user', 'content': user_input}]},
            stream_config, stream_mode='messages')

        printer = ChuckPrinter()
        for message_chunk, metadata in graph_output:
            printer.update(message_chunk, metadata)

        print()

    if args.output_path:
        state = agent.get_state(stream_config)
        output_data = {
            'config_path': args.config_path,
            'messages': convert_to_openai_messages(
                state.values['messages'], ensure_ascii=False)
        }
        with open(args.output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
