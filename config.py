import os

def load_env():
    """Simple .env loader to avoid dependencies."""
    env_path = ".env"
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
                    # Strip matching quotes if present
                    if len(value) >= 2 and ((value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'"))):
                        value = value[1:-1]
                    os.environ[key] = value

load_env()

CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = os.getenv("CLICKHOUSE_PORT", "8123")
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "password")
CLICKHOUSE_URL = f"http://{CLICKHOUSE_USER}:{CLICKHOUSE_PASSWORD}@{CLICKHOUSE_HOST}:{CLICKHOUSE_PORT}"

# Helper lambdas for query generation
def email_filter(val):
    if '@' not in val: return None
    u, d = val.split('@', 1)
    return "domain = {domain:String} AND user = {user:String}", {"domain": d, "user": u}

def domain_filter(val):
    return "domain = {domain:String}", {"domain": val}

def exact_match_filter(col):
    return lambda val: (f"{col} = {{val:String}}", {"val": val})

def wildcard_filter(col):
    return lambda val: (f"{col} LIKE {{val:String}}", {"val": val})

# Common extraction command template
# We use a awk script to be extremely fast and robust against shell parsing issues
AWK_TEMPLATE = """
awk -F'\\037' '
{
    f = $1
    # $2 is offset:match
    idx = index($2, ":")
    if (idx > 0) {
        o = substr($2, 1, idx - 1)
        m = substr($2, idx + 1)
        
        # Escape quotes
        gsub(\"\\\"\", \"\\\"\\\"\", f)

        # Standard CSV output
        print \"\\\"\" f \"\\\",\" o \",\\\"\" m \"\\\"\"
    }
}'
""".strip()
def get_extract_cmd(regex):
    # Escape single quotes for shell
    safe_regex = regex.replace("'", r"'\\''")
    # Added --null to grep and tr to replace nulls with Unit Separator (octal 037)
    return f"tr '\\n' '\\0' | xargs -0 grep -H -r -b -o -P -a --null '{safe_regex}' | tr '\\0' '\\037' | {AWK_TEMPLATE}"

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
                "help": "Search for emails in domain with wildcard (e.g. %%.com)",
                "filter": wildcard_filter("domain")
            },
            "user": {
                "arg": "--user",
                "help": "Search for emails by username (slow - see README for tuning)",
                "filter": exact_match_filter("user")
            },
            "user_wildcard": {
                "arg": "--user-wildcard",
                "help": "Search for emails by username with wildcard (slow - see README for tuning)",
                "filter": wildcard_filter("user")
            }
        }
    },
    # "domains" schema: Captures domains that are NOT part of an email address.
    # This is useful for finding URLs, URIs, domains in source code, logs, strings in binaries, cookies, etc.
    # It uses a negative lookbehind (?<!@) to ignore domains immediately preceded by an '@'.
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
            SETTINGS index_granularity = 8192
        """,
        "extract_command": get_extract_cmd(r"(?<![a-zA-Z0-9.-@])\b[a-zA-Z0-9.-]{1,256}\.[a-zA-Z]{2,32}\b"),
        "result_format": "domain",
        "highlight_regex": r"(?<![a-zA-Z0-9.-@])\b[a-zA-Z0-9.-]{1,256}\.[a-zA-Z]{2,32}\b",
        "queries": {
            "domain": {
                "arg": "--domain",
                "help": "Search for exact *standalone* domain (structure similar to a domain and is not part of an email address).",
                "filter": domain_filter
            },
            "domain_wildcard": {
                "arg": "--domain-wildcard",
                "help": "Search for *standalone* domain with wildcard (e.g. %%.org or com.android.%%)",
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
                "help": "Search for exact IP",
                "filter": exact_match_filter("ip")
            },
            "ip_wildcard": {
                "arg": "--ip-wildcard",
                "help": "Search for IP with wildcard",
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
                "help": "Search for UUID",
                "filter": exact_match_filter("uuid")
            },
            "uuid_wildcard": {
                "arg": "--uuid-wildcard",
                "help": "Search for UUID with wildcard",
                "filter": wildcard_filter("uuid")
            }
        }
    }
}
