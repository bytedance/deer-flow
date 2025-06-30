# Utilities

## Benchmark - Raccoon 64 Ti

Run the benchmark with the given agent on the given dataset.

### Get answers

1. Edit `raccoon_benchmark_{config_name}.json`.

2. Run `PYTHONPATH=src PYTHONUTF8=1 python src/fvg/utils/benchmark.py -c raccoon_benchmark_{config_name}.json -o output_answers.xlsx -m output_messages.json`.

### Scoring

1. Edit the "scoring" part of `raccoon_benchmark_{config_name}.json` with correct LLM key and answer file.

2. Run `python src/fvg/utils/raccoon_scoring.py -c raccoon_benchmark_{config_name}.json.json` to get the score.

3. Record the score into the config by the key `"score"`.
