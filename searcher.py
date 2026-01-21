#!/usr/bin/env -S uv run
import argparse
import sys
import re
import json
import config
from db import run_query

def get_results(table_name, match_expr, where_clause, query_params, limit=10):
    query = f"""
        SELECT file_path, offset, {match_expr} as match 
        FROM {table_name} 
        WHERE {where_clause} 
        LIMIT {limit}
    """
    rows = run_query(query, query_params)
    return [{"file_path": r[0], "offset": r[1], "match": r[2]} for r in rows]

def read_context(file_path, start_offset, end_offset, l_context=64, r_context=128):
    try:
        with open(file_path, 'rb') as f:
            read_start = max(0, start_offset - l_context) 
            f.seek(read_start)
            data = f.read((end_offset - start_offset) + l_context + r_context)
            return data.decode('utf-8', errors='replace'), read_start
    except Exception as e:
        return f"[Error: {e}]", 0

def main():
    parser = argparse.ArgumentParser(description="Search indexed data.")
    parser.add_argument("--limit", type=int, default=10, help="Limit results (Default: 10)")
    parser.add_argument("--left-offset", type=int, default=64)
    parser.add_argument("--right-offset", type=int, default=128)
    parser.add_argument("--json", action="store_true")

    arg_map = {}
    for s_name, schema in config.SCHEMAS.items():
        group = parser.add_argument_group(f"Schema '{s_name}'")
        for key, q_conf in schema['queries'].items():
            dest = f"{s_name}_{key}"
            group.add_argument(
                q_conf['arg'], 
                dest=dest, 
                help=q_conf.get('help')
            )
            arg_map[dest] = (s_name, q_conf)

    args = parser.parse_args()
    
    active_schema, where_clause, params = None, None, {}
    search_type = None
    search_query = None

    for dest, (s_name, q_conf) in arg_map.items():
        val = getattr(args, dest)
        if val:
            active_schema = s_name
            res = q_conf['filter'](val)
            search_type = dest
            search_query = val
            if res:
                where_clause, params = res
            else:
                # Add this error handling
                print(f"Error: Invalid input for {q_conf['arg']}. Please check your format.", file=sys.stderr)
                sys.exit(1)
            break

    if not active_schema or not where_clause:
        parser.print_help()
        return

    schema_def = config.SCHEMAS[active_schema]
    highlight_regex_str = schema_def.get('highlight_regex', '')

    results = get_results(schema_def['table_name'], schema_def['result_format'], where_clause, params, args.limit)

    if args.json:
        for row in results:
            # Note: Ensure read_context returns (data, start_offset)
            ctx, _ = read_context(row['file_path'], row['offset'], row['offset']+len(row['match']), args.left_offset, args.right_offset)
            row['context'] = ctx
            row['search_type'] = search_type
            row['search_query'] = search_query
            print(json.dumps(row))
    else:
        schema_pattern = re.compile(highlight_regex_str, re.IGNORECASE) if highlight_regex_str else None

        for row in results:
            fpath = row['file_path']
            db_offset = row['offset']
            match_str = row['match']
            match_len = len(match_str)
            
            ctx, context_start_offset = read_context(fpath, db_offset, db_offset + match_len, args.left_offset, args.right_offset)

            target_rel_start = db_offset - context_start_offset
            target_rel_end = target_rel_start + match_len

            def colorize(m):
                ms, me = m.start(), m.end()
                text = m.group(0)
                if ms == target_rel_start and me == target_rel_end and text == match_str:
                    return f"\033[32m{text}\033[0m" 
                if text == match_str:
                    return f"\033[34m{text}\033[0m" 
                return f"\033[31m{text}\033[0m" 

            if schema_pattern:
                ctx_colored = schema_pattern.sub(colorize, ctx)
            else:
                ctx_colored = ctx.replace(match_str, f"\033[32m{match_str}\033[0m")

            print(f"--- {fpath} | offset {db_offset} ---")
            print(ctx_colored)
            print("-" * 40)
    
    if len(results) == args.limit and not args.json:
        print(f"\n[Note] Reached limit of {args.limit} results. Use --limit to see more.")

if __name__ == "__main__":
    main()