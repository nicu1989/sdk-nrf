#!/usr/bin/env python3
#
# Copyright (c) 2026 Nordic Semiconductor ASA
#
# SPDX-License-Identifier: LicenseRef-Nordic-5-Clause

'''
Helpers for CI workflows that run the SBOM tool across the full repository.
'''

from __future__ import annotations

import argparse
import heapq
import json
import subprocess
from pathlib import Path


def positive_int(value: str) -> int:
    '''Parse a positive integer argument.'''
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError('value must be greater than zero')
    return parsed


def repository_root() -> Path:
    '''Return the git repository root for the current working directory.'''
    process = subprocess.run(
        ('git', 'rev-parse', '--show-toplevel'),
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(process.stdout.strip()).resolve()


def tracked_files(root: Path) -> list[tuple[str, int]]:
    '''Return tracked files that exist in the current checkout.'''
    process = subprocess.run(
        ('git', '-c', 'core.quotepath=off', 'ls-files', '-z'),
        cwd=root,
        check=True,
        capture_output=True,
    )
    files = []
    for raw_path in process.stdout.split(b'\0'):
        if len(raw_path) == 0:
            continue
        rel_path = raw_path.decode('utf-8', errors='surrogateescape')
        file_path = root / rel_path
        if not file_path.is_file():
            continue
        files.append((Path(rel_path).as_posix(), file_path.stat().st_size))
    return files


def assign_files_to_shards(files: list[tuple[str, int]], shard_count: int) -> list[list[str]]:
    '''Balance files across shards using a greedy size-based assignment.'''
    shards = [[] for _ in range(shard_count)]
    heap = [(0, 0, shard_index) for shard_index in range(shard_count)]
    heapq.heapify(heap)
    for rel_path, size in sorted(files, key=lambda item: (-item[1], item[0])):
        total_size, file_count, shard_index = heapq.heappop(heap)
        shards[shard_index].append(rel_path)
        heapq.heappush(heap, (total_size + size, file_count + 1, shard_index))
    for shard in shards:
        shard.sort()
    return shards


def write_list_file(output: Path, files: list[str]) -> None:
    '''Write one relative path per line.'''
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        ''.join(f'{file_path}\n' for file_path in files),
        encoding='utf-8',
    )


def command_matrix(args: argparse.Namespace) -> int:
    '''Print dynamic matrix JSON for GitHub Actions.'''
    matrix = {'include': [{'shard_index': index} for index in range(args.shards)]}
    print(json.dumps(matrix, separators=(',', ':')))
    return 0


def command_list_files(args: argparse.Namespace) -> int:
    '''Write the full file list or one shard file list.'''
    root = repository_root()
    files = tracked_files(root)
    rel_paths = sorted(path for path, _ in files)
    if args.shards is not None:
        if args.shard_index is None:
            raise ValueError('--shard-index is required when --shards is used')
        if args.shard_index >= args.shards:
            raise ValueError('--shard-index must be smaller than --shards')
        rel_paths = assign_files_to_shards(files, args.shards)[args.shard_index]
    elif args.shard_index is not None:
        raise ValueError('--shard-index requires --shards')
    write_list_file(Path(args.output), rel_paths)
    print(f'Wrote {len(rel_paths)} file(s) to {args.output}')
    return 0


def command_merge_cache(args: argparse.Namespace) -> int:
    '''Merge one or more SBOM cache database files.'''
    merged = {'files': {}}
    for input_path in args.inputs:
        with open(input_path, encoding='utf-8') as fd:
            cache = json.load(fd)
        for rel_path, metadata in cache.get('files', {}).items():
            if rel_path in merged['files'] and merged['files'][rel_path] != metadata:
                raise ValueError(f'Conflicting cache entry for "{rel_path}" in "{input_path}"')
            merged['files'][rel_path] = metadata
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, 'w', encoding='utf-8') as fd:
        json.dump(merged, fd, indent=2, sort_keys=True)
        fd.write('\n')
    print(f'Merged {len(args.inputs)} cache file(s) into {output}')
    return 0


def build_parser() -> argparse.ArgumentParser:
    '''Create the command line parser.'''
    parser = argparse.ArgumentParser(
        description='Helpers for CI workflows that run repository-wide SBOM scans.',
        allow_abbrev=False,
    )
    subparsers = parser.add_subparsers(dest='command', required=True)

    matrix_parser = subparsers.add_parser(
        'matrix',
        help='Print a GitHub Actions matrix for the requested number of shards.',
        allow_abbrev=False,
    )
    matrix_parser.add_argument('--shards', type=positive_int, required=True)
    matrix_parser.set_defaults(func=command_matrix)

    list_files_parser = subparsers.add_parser(
        'list-files',
        help='Write the tracked file list or a single shard list.',
        allow_abbrev=False,
    )
    list_files_parser.add_argument('--output', required=True)
    list_files_parser.add_argument('--shards', type=positive_int)
    list_files_parser.add_argument('--shard-index', type=int)
    list_files_parser.set_defaults(func=command_list_files)

    merge_cache_parser = subparsers.add_parser(
        'merge-cache',
        help='Merge SBOM cache database files.',
        allow_abbrev=False,
    )
    merge_cache_parser.add_argument('--output', required=True)
    merge_cache_parser.add_argument('inputs', nargs='+')
    merge_cache_parser.set_defaults(func=command_merge_cache)

    return parser


def main() -> int:
    '''Program entry point.'''
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())
