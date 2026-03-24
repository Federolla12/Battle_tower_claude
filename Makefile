.PHONY: test benchmark

test:
	pytest -q

benchmark:
	python scripts/benchmark_rollout.py --sims 100000
