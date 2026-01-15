#!/usr/bin/python3
import argparse
import os
import sys
import subprocess
import time
import urllib.parse
from datetime import datetime
try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

from config import CLICKHOUSE_URL, SCHEMAS

# Global progress bar for rows
global_row_pbar = None

def run_query(query, quiet=True):
    cmd = ["curl", "-s", "-X", "POST", CLICKHOUSE_URL, "--data-binary", "@-"]
    result = subprocess.run(cmd, input=query, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"CURL error: {result.stderr}")
    if "Code:" in result.stdout and "Error:" in result.stdout:
        raise Exception(f"ClickHouse error: {result.stdout}")
    return result.stdout.strip()

def setup_db(schema_name, drop=False):
    schema = SCHEMAS.get(schema_name)
    if not schema:
        print(f"Error: Schema '{schema_name}' not found in config.py", file=sys.stderr)
        sys.exit(1)

    if drop:
        print(f"Dropping table {schema['table_name']}...")
        run_query(f"DROP TABLE IF EXISTS {schema['table_name']}")
        run_query(f"ALTER TABLE indexed_files DELETE WHERE schema = '{schema_name}'")

    print(f"Ensuring table {schema['table_name']} exists...")
    run_query(schema['create_table_sql'])

    # Create tracking table
    run_query("""
    CREATE TABLE IF NOT EXISTS indexed_files (
        file_path String,
        last_modified Float64,
        last_indexed DateTime DEFAULT now(),
        schema String
    ) ENGINE = ReplacingMergeTree()
    ORDER BY (schema, file_path)
    """)

def get_indexed_state(schema_name):
    """Returns a dict {file_path: last_modified} of currently indexed files."""
    try:
        # Check if table exists first
        run_query("SELECT count() FROM indexed_files")
    except:
        return {}

    print("Fetching indexed file state...")
    query = f"SELECT file_path, last_modified FROM indexed_files WHERE schema = '{schema_name}' FORMAT JSON"
    cmd = ["curl", "-s", "-X", "POST", CLICKHOUSE_URL, "--data-binary", query]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    try:
        import json
        data = json.loads(result.stdout)
        return {row['file_path']: row['last_modified'] for row in data.get('data', [])}
    except:
        return {}

def scan_directory(root_dir):
    """Yields (path, mtime, size, inode) for all files in directory."""
    for root, dirs, files in os.walk(root_dir):
        for name in files:
            path = os.path.join(root, name)
            # Skip hidden files or internal metadata
            if "/." in path: 
                continue
            try:
                stat = os.stat(path)
                yield os.path.abspath(path), stat.st_mtime, stat.st_size, stat.st_ino
            except OSError:
                pass

def upload_batch(url, batch_data):
    cmd = ["curl", "-s", "-X", "POST", url, "--data-binary", "@-"]
    proc = subprocess.run(cmd, input=batch_data, capture_output=True)
    if proc.returncode != 0 or b"Code:" in proc.stdout:
        print(f"Upload Error: {proc.stdout.decode('utf-8', errors='ignore')}", file=sys.stderr)
        return False
    return True

def process_batch(schema_name, files_chunk, schema_config, pbar=None, batch_size_bytes=0):
    """
    1. Delete old rows for these files if they exist.
    2. Run extraction.
    3. Upload to DB in row-based batches for progress and stability.
    4. Update indexed_files.
    """
    global global_row_pbar
    table = schema_config['table_name']
    
    # 1. Cleanup old data (Optimized delete)
    quoted_files = [f"'{f.replace(chr(39), chr(92)+chr(39))}'" for f, _ in files_chunk]
    if quoted_files:
        file_list_str = ",".join(quoted_files)
        run_query(f"ALTER TABLE {table} DELETE WHERE file_path IN ({file_list_str})")

    # 2. Run extraction
    file_list_input = "\n".join([f for f, _ in files_chunk]).encode('utf-8')
    extract_cmd = schema_config['extract_command']
    
    extractor = subprocess.Popen(extract_cmd, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # 3. Stream to ClickHouse with row-based batching
    main_col = schema_config.get('main_column', 'email')
    query = f"INSERT INTO {table} (file_path, offset, {main_col}) FORMAT CSV"
    encoded_query = urllib.parse.quote(query)
    url = f"{CLICKHOUSE_URL}/?query={encoded_query}"
    
    try:
        extractor.stdin.write(file_list_input)
        extractor.stdin.close()
    except Exception as e:
        print(f"Error writing to extractor: {e}", file=sys.stderr)
        extractor.kill()
        return 0

    batch = []
    BATCH_ROWS = 1_000_000
    total_batch_rows = 0
    
    for line in extractor.stdout:
        batch.append(line)
        total_batch_rows += 1
        if len(batch) >= BATCH_ROWS:
            if not upload_batch(url, b"".join(batch)):
                extractor.kill()
                return 0
            if global_row_pbar is not None:
                global_row_pbar.update(len(batch))
            
            # Update batch pbar description to show activity
            if pbar:
                mb_str = f"{batch_size_bytes//1024//1024}MB"
                pbar.set_description(f"Batch ({len(files_chunk)} files, {mb_str}) - {total_batch_rows} rows")

            batch = []

    if batch:
        if not upload_batch(url, b"".join(batch)):
            extractor.kill()
            return 0
        if global_row_pbar is not None:
            global_row_pbar.update(len(batch))

    extractor.wait()
    
    if extractor.returncode != 0 and extractor.returncode != 1:
         # print(f"Extractor finished with code {extractor.returncode}")
         pass

    # 4. Update tracking table
    values = []
    for f, mtime in files_chunk:
        safe_f = f.replace("'", "\\'" )
        values.append(f"('{safe_f}', {mtime}, now(), '{schema_name}')")
    
    if values:
        insert_sql = f"INSERT INTO indexed_files (file_path, last_modified, last_indexed, schema) VALUES {','.join(values)}"
        run_query(insert_sql)

    return len(files_chunk)

def main():
    parser = argparse.ArgumentParser(description="Incremental Loader for Super Fast Dumpster Diver")
    parser.add_argument("path", help="Directory to scan")
    parser.add_argument("--schema", default="emails", help="Schema to use (defined in config.py)")
    parser.add_argument("--reindex", action="store_true", help="Force reindexing of all files")
    parser.add_argument("--clean", action="store_true", help="Drop existing table and start fresh")
    args = parser.parse_args()

    # Wait for DB
    for _ in range(5):
        try:
            run_query("SELECT 1")
            break
        except:
            time.sleep(1)
            print("Waiting for ClickHouse...")
    else:
        print("ClickHouse not available.", file=sys.stderr)
        sys.exit(1)

    setup_db(args.schema, drop=args.clean)
    
    schema_config = SCHEMAS.get(args.schema)
    
    # Get current state
    if args.reindex or args.clean:
        indexed_state = {}
    else:
        indexed_state = get_indexed_state(args.schema)

    # Warmup cache
    print(f"Warming up cache for {args.path}...")
    subprocess.run(["du", "-s", args.path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print(f"Scanning {args.path}...")
    
    # Discovery phase
    all_files = []
    files_seen = set()
    total_size_to_process = 0
    
    discovery_pbar = None
    if tqdm:
        discovery_pbar = tqdm(desc="Discovering files", unit="files")
        
    for fpath, mtime, size, inode in scan_directory(args.path):
        files_seen.add(fpath)
        if discovery_pbar is not None:
            if len(files_seen) % 1000 == 0:
                discovery_pbar.update(1000)
            
        # Check if needs update
        needs_update = True
        if fpath in indexed_state:
            if abs(mtime - indexed_state[fpath]) < 0.001:
                needs_update = False
        
        if needs_update:
            all_files.append((fpath, mtime, size, inode))
            total_size_to_process += size
            
    if discovery_pbar is not None:
        remaining = len(files_seen) % 1000
        if remaining > 0:
            discovery_pbar.update(remaining)
        discovery_pbar.close()

    # Sort files by inode (disk locality) to maximize sequential read performance
    all_files.sort(key=lambda x: x[3])

    print(f"Found {len(all_files)} new/modified files ({total_size_to_process//1024//1024} MB) to index.")

    global global_row_pbar
    if tqdm:
        global_row_pbar = tqdm(unit="rows", desc="Ingesting", mininterval=1.0)

    # We batch files for processing (e.g. 1000 files at a time to keep grep command efficient but not OOM)
    BATCH_SIZE = 1000 
    BATCH_SIZE_BYTES = 1024 * 1024 * 1024 # 1GB
    current_batch = []
    current_batch_size = 0
    
    processed_count = 0
    
    scan_pbar = None
    if tqdm:
        scan_pbar = tqdm(total=total_size_to_process, desc="Indexing", unit="B", unit_scale=True, unit_divisor=1024)

    for fpath, mtime, size, inode in all_files:
        current_batch.append((fpath, mtime))
        current_batch_size += size
        
        if len(current_batch) >= BATCH_SIZE or current_batch_size >= BATCH_SIZE_BYTES:
            if scan_pbar is not None:
                scan_pbar.set_description(f"Batch ({len(current_batch)} files, {current_batch_size//1024//1024}MB)")
            
            process_batch(args.schema, current_batch, schema_config, scan_pbar, current_batch_size)
            
            if scan_pbar is not None:
                scan_pbar.update(current_batch_size)
                scan_pbar.set_description("Indexing")
                
            processed_count += len(current_batch)
            current_batch = []
            current_batch_size = 0

    # Process remaining
    if current_batch:
        if scan_pbar is not None:
             scan_pbar.set_description(f"Batch ({len(current_batch)} files, {current_batch_size//1024//1024}MB)")
        process_batch(args.schema, current_batch, schema_config, scan_pbar, current_batch_size)
        if scan_pbar is not None:
            scan_pbar.update(current_batch_size)
        processed_count += len(current_batch)

    if tqdm:
        if scan_pbar is not None:
            scan_pbar.close()
        if global_row_pbar is not None:
            global_row_pbar.close()

    # Cleanup removed files
    # If we are not in reindex/clean mode, we should check for files that are in DB but not on disk
    if not args.reindex and not args.clean and indexed_state:
        # This can be slow if indexed_state is huge (millions). 
        # But python sets are fast.
        to_remove = set(indexed_state.keys()) - files_seen
        if to_remove:
            print(f"Removing {len(to_remove)} deleted files from index...")
            # Delete in chunks
            remove_list = list(to_remove)
            CHUNK = 1000
            for i in range(0, len(remove_list), CHUNK):
                chunk = remove_list[i:i+CHUNK]
                quoted = [f"'{f.replace(chr(39), chr(92)+chr(39))}'" for f in chunk]
                run_query(f"ALTER TABLE {schema_config['table_name']} DELETE WHERE file_path IN ({','.join(quoted)})")
                run_query(f"ALTER TABLE indexed_files DELETE WHERE schema='{args.schema}' AND file_path IN ({','.join(quoted)})")

    print(f"Finished. Processed {processed_count} files.")

if __name__ == "__main__":
    main()