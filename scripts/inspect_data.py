#!/usr/bin/env python3
"""Backward-compatible dataset inspection command."""

import argparse
import json
import sys

for stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

from dataease_skill.client import DataEaseClient
from dataease_skill.config import Settings
from dataease_skill.datasets import DatasetService
from dataease_skill.errors import DataEaseError


def main() -> None:
    parser = argparse.ArgumentParser(description="查询 DataEase 数据集与字段")
    parser.add_argument("--list-datasets", action="store_true")
    parser.add_argument("--dataset")
    parser.add_argument("--profile", action="store_true", help="返回字段语义画像")
    args = parser.parse_args()
    if not args.list_datasets and not args.dataset:
        parser.error("请使用 --list-datasets 或 --dataset")
    try:
        with DataEaseClient(Settings.load()) as client:
            service = DatasetService(client)
            if args.list_datasets:
                result = [
                    {"name": item.get("name"), "id": str(item.get("id")), "path": item.get("path")}
                    for item in service.list()
                ]
            elif args.profile:
                result = service.profile(args.dataset)
            else:
                dataset, fields = service.fields(args.dataset)
                result = {
                    "dataset": {"name": dataset.get("name"), "id": str(dataset.get("id"))},
                    "fields": fields,
                }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except DataEaseError as exc:
        print(json.dumps({"ok": False, "error": exc.to_dict()}, ensure_ascii=False, indent=2))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
