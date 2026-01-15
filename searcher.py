#!/usr/bin/python3
import argparse
import sys
import subprocess
import json
import re

CLICKHOUSE_URL = "http://default:password@localhost:8123"

def get_results(where_clause, limit=10):
    # Reconstruct email from user and domain columns
    query = f"""
        SELECT file_path, offset, concat(user, '@', domain) as email 
        FROM emails 
        WHERE {where_clause} 
        LIMIT {limit} 
        FORMAT JSON
    """
    cmd = ["curl", "-s", "-X", "POST", CLICKHOUSE_URL, "--data-binary", query]
    res = subprocess.run(cmd, capture_output=True, text=True)
    try:
        data = json.loads(res.stdout)
        return data.get('data', [])
    except:
        print(f"Error querying DB: {res.stdout}")
        return []

def read_context(file_path, start_offset, end_offset, l_context_bytes=64, r_context_bytes=128):
    try:
        with open(file_path, 'rb') as f:
            read_start = max(0, start_offset - l_context_bytes) 
            
            # Seek and read
            f.seek(read_start)
            chunk_len = (end_offset - start_offset) + (l_context_bytes + r_context_bytes)
            data = f.read(chunk_len)
            data = data.decode('latin-1')
            return data
    except Exception as e:
        return f"[Error reading file: {e}]"

def main():
    parser = argparse.ArgumentParser(description="Search indexed emails.")
    parser.add_argument("--email", help="Exact email to search")
    parser.add_argument("--domain", help="Domain to search (e.g., gmail.com)")
    parser.add_argument("--user", help="Username to search (e.g., 'john.doe' in john.doe@gmail.com)")
    parser.add_argument("--wildcard", help="SQL LIKE pattern for domain (e.g., %%hotmail%%)")
    parser.add_argument("--limit", type=int, default=10, help="Max number of results (default: 10)")
    parser.add_argument("--left-offset", type=int, default=64, help="Bytes to read before the match (default: 64)")
    parser.add_argument("--right-offset", type=int, default=128, help="Bytes to read after the match (default: 128)")
    parser.add_argument("--json", action="store_true", help="Output results as JSON (one object per line)"
    )


    
    args = parser.parse_args()
    
    where = None
    if args.email:
        if '@' in args.email:
            try:
                user_part, domain_part = args.email.split('@', 1)
                # Fast path: hits (domain, user) index
                where = f"domain = '{domain_part}' AND user = '{user_part}'"
            except IndexError:
                print("Invalid email format.")
                return
        else:
            print("Please provide a full email address for --email.")
            return
    elif args.domain:
        # Fast path: hits (domain, user) index prefix
        where = f"domain = '{args.domain}'"
    elif args.user:
        # Slower path (but optimized with Bloom Filter)
        where = f"user = '{args.user}'"
    elif args.wildcard:
        # Slower path: domain LIKE
        where = f"domain LIKE '{args.wildcard}'"
    else:
        print("Please provide --email, --domain, --user, or --wildcard")
        return

    results = get_results(where, limit=args.limit)
    
    if not results:
        print("No results found.")
        return

    print(f"Found {len(results)} matches:\n")
    for row in results:
        fpath = row['file_path']
        start = row['offset']
        email = row['email']
        end = start+len(email)
        
        context = read_context(fpath, start, end, l_context_bytes=args.left_offset, r_context_bytes=args.right_offset)

        if args.json:
            output = {
                "email": email,
                "file_path": fpath,
                "offset_start": start,
                "offset_end": end,
                "left_offset": args.left_offset,
                "right_offset": args.right_offset,
                "context": context,
            }
            print(json.dumps(output, ensure_ascii=False))
        else:
            # for highlighting (TTY mode)
            pattern = re.compile(r'[a-z0-9._%+-]{1,300}@[a-z0-9.-]{1,300}\.[a-z]{2,8}')
            context_start_offset = max(0, start - args.left_offset)
            target_rel_start = start - context_start_offset
            target_rel_end = target_rel_start + len(email)

            def colorize(match):
                m = match.group(0)
                s, e = match.start(), match.end()

                if m == email:
                    if s == target_rel_start and e == target_rel_end:
                        return f"\033[32m{m}\033[0m"   # exact hit at offset
                    else:
                        return f"\033[34m{m}\033[0m"    # same email elsewhere
                else:
                    return f"\033[31m{m}\033[0m"         # other emails (optional)

            context_colored = pattern.sub(colorize, context)

            print(f"{fpath} (Offsets {start}-{end}):")
            print(context_colored)
            print("-" * 40)


if __name__ == "__main__":
    main()
