"""Local demonstration; partitions are executed sequentially, not in AWS."""

import argparse
import json
from pathlib import Path

from graphword.graph import build_partition, merge_partitions, shortest_path, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="GraphWord local graph demonstration")
    parser.add_argument("dictionary", type=Path)
    parser.add_argument("--partitions", type=int, default=1)
    parser.add_argument("--from", dest="start")
    parser.add_argument("--to", dest="end")
    args = parser.parse_args()
    if not 1 <= args.partitions <= 64:
        parser.error("partitions must be between 1 and 64")
    if (args.start is None) != (args.end is None):
        parser.error("--from and --to must be supplied together")
    try:
        words = args.dictionary.read_text(encoding="utf-8").splitlines()
        graph = merge_partitions(
            build_partition(words, index, args.partitions)
            for index in range(args.partitions)
        )
        result = summary(graph)
        result["execution"] = "local-sequential"
        result["partitions"] = args.partitions
        if args.start is not None:
            result["shortest_path"] = shortest_path(graph, args.start, args.end)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
