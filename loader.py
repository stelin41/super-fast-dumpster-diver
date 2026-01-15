#!/usr/bin/python3
import subprocess
import time
import sys
import urllib.parse
import os
import argparse
try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

CLICKHOUSE_URL = "http://default:password@localhost:8123"

def run_query(query):
    cmd = ["curl", "-s", "-X", "POST", CLICKHOUSE_URL, "--data-binary", query]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"CURL error: {result.stderr}")
    if "Code:" in result.stdout and "Error:" in result.stdout:
        raise Exception(f"ClickHouse error: {result.stdout}")
    return result.stdout.strip()

def setup_db():
    print("Setting up database...")
    run_query("DROP TABLE IF EXISTS emails")

    # LowCardinality(String) for file_path is CRITICAL for 1TB scale.
    # It turns repetitive strings into 2-byte or 4-byte integers + a dictionary.
    # ORDER BY (domain, email) ensures that searches for domains and emails are lightning fast.
    create_table_sql = """
    CREATE TABLE emails (
        file_path LowCardinality(String),
        offset UInt64,
        email String EPHEMERAL,
        user String DEFAULT substring(email, 1, minus(position(email, '@'), 1)),
        domain String DEFAULT substring(email, position(email, '@') + 1),
        INDEX user_bf user TYPE bloom_filter(0.01) GRANULARITY 1
    ) ENGINE = MergeTree()
    ORDER BY (domain, user)
    SETTINGS index_granularity = 8192
    """

    run_query(create_table_sql)
    print("Table 'emails' created.")

def upload_batch(url, batch_data):
    """Uploads a chunk of data to ClickHouse using curl."""
    cmd = ["curl", "-s", "-X", "POST", url, "--data-binary", "@-"]
    # Pass batch_data (bytes) to curl's stdin
    proc = subprocess.run(cmd, input=batch_data, capture_output=True)
    
    if proc.returncode != 0:
        print(f"Batch upload failed (curl error): {proc.stderr.decode(errors='replace')}")
        return False
    if b"Code:" in proc.stdout or b"Error:" in proc.stdout or b"Exception" in proc.stdout:
        print(f"Batch upload failed (ClickHouse error): {proc.stdout.decode(errors='replace')}")
        return False
    return True

def load_csv(source, is_command=False):
    BATCH_SIZE = 1_000_000  # Process 1M rows at a time to avoid OOM

    if not is_command and not os.path.exists(source):
        print(f"File {source} not found.")
        return

    # Prepare ClickHouse URL
    query = "INSERT INTO emails (file_path, offset, email) FORMAT CSV"
    encoded_query = urllib.parse.quote(query)
    url = f"{CLICKHOUSE_URL}/?query={encoded_query}"

    print(f"Streaming {source} to ClickHouse in batches of {BATCH_SIZE} rows...")
    
    start_time = time.time()
    total_rows = 0
    
    # Open input stream (command stdout or file)
    if is_command:
        # Use a large buffer for pipe
        proc = subprocess.Popen(source, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1024*1024)
        input_stream = proc.stdout
    else:
        proc = None
        input_stream = open(source, 'rb')

    batch = []

    if tqdm:
        input_stream = tqdm(input_stream, miniters=1, mininterval=5., unit="row", desc="Ingesting")
    
    try:
        for line in input_stream:
            batch.append(line)
            if len(batch) >= BATCH_SIZE:
                # Join bytes and upload
                if upload_batch(url, b"".join(batch)):
                    total_rows += len(batch)
                    if not tqdm:
                        print(f"Uploaded batch. Total rows so far: {total_rows}")
                else:
                    print("Stopping due to upload error.")
                    break
                batch = [] # Reset batch

        # Upload remaining rows
        if batch:
            if upload_batch(url, b"".join(batch)):
                total_rows += len(batch)
                print(f"Uploaded final batch. Total rows: {total_rows}")
            
    except KeyboardInterrupt:
        print("\nInterrupted by user. Committing handled batches...")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if proc:
            proc.terminate()
        elif input_stream:
            input_stream.close()

    end_time = time.time()
    duration = end_time - start_time
    
    # Final count check
    try:
        count = run_query("SELECT count() FROM emails")
        print(f"Process finished in {duration:.2f}s. Total rows in DB: {count}")
    except:
        print("Could not query final count.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load data into ClickHouse.")
    parser.add_argument("source", nargs='?', default="input.csv", help="Path to CSV file or command to execute")
    parser.add_argument("--command", action="store_true", help="If set, 'source' is treated as a shell command")
    args = parser.parse_args()

    # Wait for CH
    for _ in range(15):
        try:
            run_query("SELECT 1")
            break
        except:
            time.sleep(1)
    else:
        print("ClickHouse not responding.")
        sys.exit(1)

    setup_db()
    load_csv(args.source, args.command)
