#!/usr/bin/env -S uv run
import argparse
import os
import sys
import subprocess
import time
from tqdm import tqdm

import config
from db import get_client, run_query

# Define at module level so it's accessible globally
global_row_pbar = None

def setup_db(schema_key, drop=False):
    """
    schema_key: the key from config.SCHEMAS (e.g., 'emails')
    """
    schema_conf = config.SCHEMAS.get(schema_key)
    table_name = schema_conf['table_name']

    # 1. Always ensure the tracking table exists first
    run_query("""
    CREATE TABLE IF NOT EXISTS indexed_files (
        file_path String,
        last_modified Float64,
        last_indexed DateTime DEFAULT now(),
        schema String
    ) ENGINE = ReplacingMergeTree()
    ORDER BY (schema, file_path)
    """)

    # 2. If --clean is used, wipe the specific data
    if drop:
        print(f"Cleaning all data for schema: {schema_key}...")
        run_query(f"DROP TABLE IF EXISTS {table_name}")
        # Wipe the index history for this specific schema
        run_query("ALTER TABLE indexed_files DELETE WHERE schema = %(s)s", {"s": table_name})

    # 3. Create/Ensure the main data table exists
    run_query(schema_conf['create_table_sql'])

def get_indexed_state(schema_name):
    try:
        rows = run_query(
            "SELECT file_path, last_modified FROM indexed_files WHERE schema = %(s)s",
            {"s": schema_name}
        )
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}

def scan_directory(target_path):
    target_path = os.path.realpath(target_path)
    if os.path.isfile(target_path):
        stat = os.stat(target_path)
        yield target_path, stat.st_mtime, stat.st_size, stat.st_ino
        return

    for root, _, files in os.walk(target_path):
        for name in files:
            path = os.path.join(root, name)
            try:
                stat = os.stat(path)
                # Use realpath to ensure consistent keys in the database
                yield os.path.realpath(path), stat.st_mtime, stat.st_size, stat.st_ino
            except OSError:
                pass

def process_batch(schema_name, files_chunk, schema_config, scan_pbar=None, batch_size_bytes=0):
    global global_row_pbar
    table = schema_config['table_name']
    files_list = [f for f, _ in files_chunk]

    # 1. Cleanup old data for these specific files before re-inserting
    if files_list:
        run_query(f"ALTER TABLE {table} DELETE WHERE file_path IN %(files)s", {"files": files_list})

    # 2. Start Extractor
    file_list_input = "\n".join(files_list).encode('utf-8')
    extract_cmd = schema_config['extract_command']
    extractor = subprocess.Popen(
        extract_cmd,
        shell=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        bufsize=1024*1024
    )

    try:
        if extractor.stdin:
            extractor.stdin.write(file_list_input)
            extractor.stdin.close()
        
        main_col = schema_config.get('main_column')
        client = get_client()

        if scan_pbar:
            mb = batch_size_bytes / (1024 * 1024)
            scan_pbar.set_description(f"Batch: {len(files_list)} files ({mb:.1f} MB)")

        # 3. Wrapper Generator to track rows/s in real-time
        def tracked_generator():
            if extractor.stdout:
                for line in extractor.stdout:
                    parts = line.decode('utf-8', 'ignore').rstrip('\n').split('\037')
                    if len(parts) == 3:
                        if global_row_pbar is not None:
                            global_row_pbar.update(1)
                        yield (parts[0], int(parts[1]), parts[2])

        client.execute(
            f"INSERT INTO {table} (file_path, offset, {main_col}) VALUES",
            tracked_generator()
        )
        
    except Exception as e:
        print(f"\n[!] Error during streaming ingest: {e}", file=sys.stderr)
        extractor.kill()
    finally:
        extractor.wait()

    # 4. Update tracking table
    tracking_rows = [(f, m, schema_name) for f, m in files_chunk]
    run_query("INSERT INTO indexed_files (file_path, last_modified, schema) VALUES", tracking_rows)

def main():
    global global_row_pbar
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--schema", default="emails")
    parser.add_argument("--reindex", action="store_true")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    schema_conf = config.SCHEMAS.get(args.schema)
    if not schema_conf:
        print(f"Error: Schema '{args.schema}' not found.")
        sys.exit(1)
    
    table_id = schema_conf['table_name']
    setup_db(table_id, drop=args.clean)
    
    indexed_state = {} if (args.reindex or args.clean) else get_indexed_state(table_id)

    # Warmup cache, it significantly speeds up the discovery phase
    print(f"Warming up cache for {args.path} ...")
    subprocess.run(["du", "-s", args.path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    all_files, total_bytes = [], 0
    files_seen = set()
    discovery_pbar = tqdm(desc="Scanning", unit="files")
    for fpath, mtime, size, inode in scan_directory(args.path):
        discovery_pbar.update(1)
        files_seen.add(fpath)
        # Check if file is new or modified
        if fpath not in indexed_state or abs(mtime - indexed_state[fpath]) > 0.001:
            all_files.append((fpath, mtime, size, inode))
            total_bytes += size
    discovery_pbar.close()

    # Cleanup removed files
    if not args.reindex and not args.clean and indexed_state:
        # We only want to remove files that are:
        # 1. Under the current path being scanned
        # 2. NO LONGER present on disk (not in files_seen)
        abs_target_path = os.path.realpath(args.path)

        to_remove = [
            fpath for fpath in indexed_state.keys()
            if fpath.startswith(abs_target_path) and fpath not in files_seen
        ]

        if to_remove:
            print(f"Removing {len(to_remove)} deleted/excluded files from index...")
            CHUNK = 1000
            for i in range(0, len(to_remove), CHUNK):
                chunk = to_remove[i : i + CHUNK]
                # Remove from data table
                run_query(f"ALTER TABLE {table_id} DELETE WHERE file_path IN %(f)s", {"f": chunk})
                # Remove from tracking table
                run_query(f"ALTER TABLE indexed_files DELETE WHERE schema = %(s)s AND file_path IN %(f)s",
                          {"s": table_id, "f": chunk})

    if not all_files:
        print("Everything is up to date.")
        return

    # Sort by inode to optimize disk read patterns
    all_files.sort(key=lambda x: x[3])
    print(f"Found {len(all_files)} files to index.")

    # --- Initialize Progress Bars ---
    main_pbar = tqdm(total=total_bytes, unit="B", unit_scale=True, position=0, desc="Overall Progress")
    global_row_pbar = tqdm(unit="rows", desc="Ingesting", position=1, leave=True)

    BATCH_SIZE_FILES = 1000
    BATCH_SIZE_BYTES = 512 * 1024 * 1024
    
    current_batch, current_batch_size = [], 0

    for fpath, mtime, size, inode in all_files:
        current_batch.append((fpath, mtime))
        current_batch_size += size
        
        if len(current_batch) >= BATCH_SIZE_FILES or current_batch_size >= BATCH_SIZE_BYTES:
            process_batch(table_id, current_batch, schema_conf, scan_pbar=main_pbar, batch_size_bytes=current_batch_size)
            main_pbar.update(current_batch_size)
            current_batch, current_batch_size = [], 0

    if current_batch:
        process_batch(table_id, current_batch, schema_conf, scan_pbar=main_pbar, batch_size_bytes=current_batch_size)
        main_pbar.update(current_batch_size)

    main_pbar.close()
    if global_row_pbar is not None:
        global_row_pbar.close()

if __name__ == "__main__":
    main()