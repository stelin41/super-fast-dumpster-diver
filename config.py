import os
import shutil

def load_env():
    """Simple .env loader to avoid dependencies."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    if len(value) >= 2 and ((value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'"))):
                        value = value[1:-1]
                    os.environ[key] = value

load_env()

# --- Grep Detection for macOS Compatibility ---
# macOS default grep is BSD; GNU Grep (ggrep) is required for Perl Regex (-P)
GREP_BIN = shutil.which("ggrep") or shutil.which("grep") or "grep"

# Native Interface settings
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "9000"))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "password")

# Updated filters to use native driver syntax: %(param)s
def email_filter(val):
    if '@' not in val: return None
    u, d = val.split('@', 1)
    return "domain = %(domain)s AND user = %(user)s", {"domain": d, "user": u}

def domain_filter(val):
    return "domain = %(domain)s", {"domain": val}

def exact_match_filter(col):
    return lambda val: (f"{col} = %(val)s", {"val": val})

def wildcard_filter(col):
    return lambda val: (f"{col} LIKE %(val)s", {"val": val})

def get_extract_cmd(regex):
    safe_regex = regex.replace("'", r"'\\''")
    # output format: `PATH\0OFFSET:MATCH`, notice the first separator is \0 and the second is :
    return f"tr '\\n' '\\0' | xargs -0 {GREP_BIN} -H -r -b -o -P -a --null '{safe_regex}' --"

SCHEMAS = {
    "emails": {
        "table_name": "emails",
        "main_column": "email",
        "create_table_sql": """
            CREATE TABLE IF NOT EXISTS emails (
                file_path LowCardinality(String),
                offset UInt64,
                email String EPHEMERAL,
                user String DEFAULT substring(email, 1, minus(position(email, '@'), 1)),
                domain String DEFAULT substring(email, position(email, '@') + 1),
                INDEX user_bf user TYPE bloom_filter(0.01) GRANULARITY 1
            ) ENGINE = MergeTree()
            ORDER BY (domain, user)
            SETTINGS index_granularity = 8192
        """,
        "extract_command": get_extract_cmd(r"[a-zA-Z0-9._%+-]{1,256}@[a-zA-Z0-9.-]{1,256}\.[a-zA-Z]{2,10}"),
        "result_format": "concat(user, '@', domain)",
        "highlight_regex": r"[a-zA-Z0-9._%+-]{1,256}@[a-zA-Z0-9.-]{1,256}\.[a-zA-Z]{2,10}",
        "queries": {
            "email": {
                "arg": "--email",
                "help": "Search for exact email",
                "filter": email_filter
            },
            "domain": {
                "arg": "--email-domain",
                "help": "Search for emails in domain",
                "filter": domain_filter
            },
            "domain_wildcard": {
                "arg": "--email-domain-wildcard",
                "help": "Search for emails in domain wildcard (Uses LIKE syntax: %% and _)",
                "filter": wildcard_filter("domain")
            },
            "user": {
                "arg": "--user",
                "help": "Search for emails by username (See README to improve performance)",
                "filter": exact_match_filter("user")
            },
            "user_wildcard": {
                "arg": "--user-wildcard",
                "help": "Search for emails by username wildcard (Uses LIKE syntax; See README to improve performance)",
                "filter": wildcard_filter("user")
            }
        }
    },
    "domains": {
        "table_name": "domains",
        "main_column": "domain",
        "create_table_sql": """
            CREATE TABLE IF NOT EXISTS domains (
                file_path LowCardinality(String),
                offset UInt64,
                domain String
            ) ENGINE = MergeTree()
            ORDER BY domain
        """,
        "extract_command": get_extract_cmd(r"(?<![a-zA-Z0-9.-@])\b[a-zA-Z0-9.-]{1,256}\.[a-zA-Z]{2,32}\b"),
        "result_format": "domain",
        "highlight_regex": r"(?<![a-zA-Z0-9.-@])\b[a-zA-Z0-9.-]{1,256}\.[a-zA-Z]{2,32}\b",
        "queries": {
            "domain": {
                "arg": "--domain",
                "help": "Search exact standalone domain (structure similar to a domain and is not part of an email address).",
                "filter": domain_filter
            },
            "domain_wildcard": {
                "arg": "--domain-wildcard",
                "help": "Wildcard standalone domain search (Uses LIKE syntax; e.g. %%.org or com.android.%%)",
                "filter": wildcard_filter("domain")
            }
        }
    },
    "ips": {
        "table_name": "ips",
        "main_column": "ip",
        "create_table_sql": """
            CREATE TABLE IF NOT EXISTS ips (
                file_path LowCardinality(String),
                offset UInt64,
                ip String
            ) ENGINE = MergeTree()
            ORDER BY ip
            SETTINGS index_granularity = 8192
        """,
        "extract_command": get_extract_cmd(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
        "result_format": "ip",
        "highlight_regex": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        "queries": {
            "ip": {
                "arg": "--ip",
                "help": "Search exact IP",
                "filter": exact_match_filter("ip")
            },
            "ip_wildcard": {
                "arg": "--ip-wildcard",
                "help": "Wildcard IP search (Uses LIKE syntax)",
                "filter": wildcard_filter("ip")
            }
        }
    },
    "uuids": {
        "table_name": "uuids",
        "main_column": "uuid",
        "create_table_sql": """
            CREATE TABLE IF NOT EXISTS uuids (
                file_path LowCardinality(String),
                offset UInt64,
                uuid String
            ) ENGINE = MergeTree()
            ORDER BY uuid
            SETTINGS index_granularity = 8192
        """,
        "extract_command": get_extract_cmd(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"),
        "result_format": "uuid",
        "highlight_regex": r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        "queries": {
            "uuid": {
                "arg": "--uuid",
                "help": "Search UUID",
                "filter": exact_match_filter("uuid")
            },
            "uuid_wildcard": {
                "arg": "--uuid-wildcard",
                "help": "Wildcard UUID search (Uses LIKE syntax)",
                "filter": wildcard_filter("uuid")
            }
        }
    }
}