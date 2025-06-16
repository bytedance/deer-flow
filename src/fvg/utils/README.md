# Utilities

## Benchmark Tool

Run the benchmark with the given agent on the given dataset.

### Get answers

Edit `benchmark_config.json`.

Run `PYTHONPATH=.:src PYTHONUTF8=1 python src/fvg/utils/benchmark.py -c benchmark_config.json -o output_answers.xlsx -m output_messages.json`.

### Count points

Edit `point_counter_config.json` with correct answer file.

Run `python src/fvg/utils/point_counter.py -c point_counter_config.json` to get the score.
