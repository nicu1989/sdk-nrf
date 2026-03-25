#!/usr/bin/env python3
#
# Copyright (c) 2026 Nordic Semiconductor ASA
#
# SPDX-License-Identifier: LicenseRef-Nordic-5-Clause

'''
Helpers for the full-repository SBOM workflow.
'''

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def repository_root() -> Path:
    '''Return the current git repository root.'''
    process = subprocess.run(
        ('git', 'rev-parse', '--show-toplevel'),
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(process.stdout.strip()).resolve()


def tracked_files(root: Path) -> list[str]:
    '''Return tracked files that exist in the checkout.'''
    process = subprocess.run(
        ('git', '-c', 'core.quotepath=off', 'ls-files', '-z'),
        cwd=root,
        check=True,
        capture_output=True,
    )
    files = []
    for raw_path in process.stdout.split(b'\0'):
        if not raw_path:
            continue
        rel_path = raw_path.decode('utf-8', errors='surrogateescape')
        if (root / rel_path).is_file():
            files.append(Path(rel_path).as_posix())
    files.sort()
    return files


def shard_files(files: list[str], shards: int, shard_index: int) -> list[str]:
    '''Return one shard of the tracked file list.'''
    return files[shard_index::shards]


def write_list_file(output: Path, files: list[str]) -> None:
    '''Write one relative path per line.'''
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(''.join(f'{path}\n' for path in files), encoding='utf-8')


def matrix_command(args: argparse.Namespace) -> int:
    '''Print matrix JSON for GitHub Actions.'''
    matrix = {'include': [{'shard_index': index} for index in range(args.shards)]}
    print(json.dumps(matrix, separators=(',', ':')))
    return 0


def list_files_command(args: argparse.Namespace) -> int:
    '''Write the full tracked file list or one shard list.'''
    files = tracked_files(repository_root())
    if args.shards is not None:
        files = shard_files(files, args.shards, args.shard_index)
    write_list_file(Path(args.output), files)
    return 0


def merge_cache_command(args: argparse.Namespace) -> int:
    '''Merge SBOM cache database files.'''
    merged = {'files': {}}
    for input_path in args.inputs:
        with open(input_path, encoding='utf-8') as fd:
            cache = json.load(fd)
        merged['files'].update(cache.get('files', {}))

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, 'w', encoding='utf-8') as fd:
        json.dump(merged, fd, indent=2, sort_keys=True)
        fd.write('\n')
    return 0


def build_parser() -> argparse.ArgumentParser:
    '''Create the command line parser.'''
    parser = argparse.ArgumentParser(
        description='Helpers for the full-repository SBOM workflow.',
        allow_abbrev=False,
    )
    subparsers = parser.add_subparsers(dest='command', required=True)

    matrix_parser = subparsers.add_parser('matrix', allow_abbrev=False)
    matrix_parser.add_argument('--shards', type=int, required=True)
    matrix_parser.set_defaults(func=matrix_command)

    list_files_parser = subparsers.add_parser('list-files', allow_abbrev=False)
    list_files_parser.add_argument('--output', required=True)
    list_files_parser.add_argument('--shards', type=int)
    list_files_parser.add_argument('--shard-index', type=int, default=0)
    list_files_parser.set_defaults(func=list_files_command)

    merge_cache_parser = subparsers.add_parser('merge-cache', allow_abbrev=False)
    merge_cache_parser.add_argument('--output', required=True)
    merge_cache_parser.add_argument('inputs', nargs='+')
    merge_cache_parser.set_defaults(func=merge_cache_command)

    return parser


def main() -> int:
    '''Program entry point.'''
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())
