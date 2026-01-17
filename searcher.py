#!/usr/bin/python3
import argparse
import sys
import subprocess
import json
import re
import urllib.parse
from config import CLICKHOUSE_URL, SCHEMAS

def get_results(table_name, match_expr, where_clause, query_params, limit=10):
    limit = int(limit)
    query = f"""
        SELECT file_path, offset, {match_expr} as match 
        FROM {table_name} 
        WHERE {where_clause} 
        LIMIT {limit} 
        FORMAT JSON
    """
    
    # ClickHouse parameters are passed as param_<name>=value in query string
    url_params = {}
    for k, v in query_params.items():
        url_params[f"param_{k}"] = v
    
    query_string = urllib.parse.urlencode(url_params)
    full_url = f"{CLICKHOUSE_URL}/?{query_string}" if query_string else CLICKHOUSE_URL

    try:
        cmd = ["curl", "-s", "-X", "POST", full_url, "--data-binary", query]
        res = subprocess.run(cmd, capture_output=True, text=True)
        
        if res.returncode != 0:
            print(f"Error querying DB (curl failed): {res.stderr}", file=sys.stderr)
            return []

        # Check for HTTP errors that curl -s might swallow (unless we check output)
        # But if it returns JSON, we try to parse it.
        try:
            data = json.loads(res.stdout)
            return data.get('data', [])
        except json.JSONDecodeError:
            print(f"Error querying DB (invalid JSON): {res.stdout}", file=sys.stderr)
            return []
            
    except Exception as e:
        print(f"Error querying DB: {e}", file=sys.stderr)
        return []

def read_context(file_path, start_offset, end_offset, l_context_bytes=64, r_context_bytes=128):
    try:
        with open(file_path, 'rb') as f:
            read_start = max(0, start_offset - l_context_bytes) 
            
            # Seek and read
            f.seek(read_start)
            chunk_len = (end_offset - start_offset) + (l_context_bytes + r_context_bytes)
            data = f.read(chunk_len)
            try:
                data = data.decode('utf-8')
            except UnicodeDecodeError:
                data = data.decode('latin-1')
            return data
    except Exception as e:
        return f"[Error reading file: {e}]"

def main():
    epilog_text = """Wildcard Support:
  For options ending in '-wildcard', standard SQL LIKE patterns are used:
  %    Matches any sequence of characters (including none).
  _    Matches any single character.

  Escaping:
  To match a literal '%', '_', or '\\', precede it with a backslash: \\%, \\_, or \\\\.
  (Note: Some shells may require double backslashes: \\\\%)

Case sensitivity:
  All searches and default regexes are case sensitive."""
    parser = argparse.ArgumentParser(
        description="Search indexed data.",
        epilog=epilog_text,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    # Global args
    parser.add_argument("--limit", type=int, default=10, help="Max number of results (default: 10)")
    parser.add_argument("--left-offset", type=int, default=64, help="Bytes to read before the match")
    parser.add_argument("--right-offset", type=int, default=128, help="Bytes to read after the match")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")

    # Dynamic args from config
    arg_map = {}

    for schema_name, schema in SCHEMAS.items():
        if 'queries' not in schema:
            continue
        
        group = parser.add_argument_group(f"Schema '{schema_name}'")
        for key, q_conf in schema['queries'].items():
            dest = f"{schema_name}_{key}"
            group.add_argument(q_conf['arg'], dest=dest, help=q_conf['help'], metavar=q_conf.get('metavar'))
            arg_map[dest] = (schema_name, q_conf)

    args = parser.parse_args()
    
    active_schema = None
    where_clause = None
    query_params = {}
    
    for dest, (s_name, q_conf) in arg_map.items():
        val = getattr(args, dest)
        if val:
            active_schema = s_name
            filter_func = q_conf.get('filter')
            if filter_func:
                result = filter_func(val)
                if result is None:
                    print(f"Invalid input for {q_conf['arg']}", file=sys.stderr)
                    return
                where_clause, query_params = result
            else:
                print(f"Configuration error: No filter defined for {q_conf['arg']}", file=sys.stderr)
                return
            break
    
    if not active_schema:
        print("Please provide a search argument (e.g., --email, --domain).", file=sys.stderr)
        parser.print_help()
        return

    schema_def = SCHEMAS[active_schema]
    table = schema_def['table_name']
    match_expr = schema_def['result_format']
    highlight_regex_str = schema_def.get('highlight_regex', '')

    results = get_results(table, match_expr, where_clause, query_params, limit=args.limit)

    if args.json:
        for row in results:
            fpath = row['file_path']
            start = row['offset']
            match_str = row['match']
            end = start + len(match_str)
            
            context = read_context(fpath, start, end, args.left_offset, args.right_offset)
            
            output = {
                "match": match_str,
                "file_path": fpath,
                "offset": start,
                "relative_offset": args.left_offset,
                "context": context,
            }
            print(json.dumps(output, ensure_ascii=False))
    else:
        if not results:
            print("No results found.")
            return

        print(f"Found {len(results)} matches in '{active_schema}':\n")
        
        schema_pattern = None
        if highlight_regex_str:
            try:
                schema_pattern = re.compile(highlight_regex_str, re.IGNORECASE)
            except re.error:
                pass

        for row in results:
            fpath = row['file_path']
            start = row['offset']
            match_str = row['match']
            match_len = len(match_str)
            end = start + match_len
            
            context = read_context(fpath, start, end, args.left_offset, args.right_offset)

            context_start_offset = max(0, start - args.left_offset)
            
            target_rel_start = start - context_start_offset
            target_rel_end = target_rel_start + match_len

            def colorize(m):
                ms = m.start()
                me = m.end()
                text = m.group(0)

                if ms == target_rel_start and me == target_rel_end and text == match_str:
                     return f"\033[32m{text}\033[0m" 
                
                if text == match_str:
                    return f"\033[34m{text}\033[0m" 
                
                return f"\033[31m{text}\033[0m" 

            if schema_pattern:
                context_colored = schema_pattern.sub(colorize, context)
            else:
                context_colored = context.replace(match_str, f"\033[32m{match_str}\033[0m")

            print(f"{fpath} (Offset {start}):")
            print(context_colored)
            print("-" * 40)
        if len(results) == args.limit:
            print(f"Reached maximum number of results, to increase it use --limit LIMIT")

if __name__ == "__main__":
    main()
