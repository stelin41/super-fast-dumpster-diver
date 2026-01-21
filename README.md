# 🗑️ Super Fast Dumpster Diver 🚀


**Simple. Hackable. Blazingly Fast.**

> "Finding a needle in a 2-billion-row haystack in an instant."

Super Fast Dumpster Diver is a minimalist tool to index and search specific patterns inside the **contents** of massive unstructured plaintext files (logs, dumps, archives, binaries) across a directory tree. It provides **instant search** on typical hardware, performing exceptionally well even on slow, spinning HDDs.

While currently designed for **cybersecurity intelligence and recon gathering**, its simple and hackable nature makes it easy to adapt for other use cases like searching massive codebases. It is designed for easy integration with other software and APIs.

## ⚡ Key Features

*   **Versatile**: Currently optimized for **emails**, standalone domains (URLs, code, logs, ...), IPs and UUIDs; but the pattern-matching loader can be easily tweaked for any regex.
*   **Efficient**: The index typically consumes up to **~20%** of the original raw data size per regex indexed.
*   **JSON Output**: Pipe-friendly JSON output for integration with other tools.
*   **Standard SQL**: The backend is just ClickHouse. You can query it with DBeaver, Grafana, or build your own API on top of it.

---

## 🏃 Quick start (typical setup)
```bash
## Setup
# Clone repository
git clone 'https://github.com/stelin41/super-fast-dumpster-diver'
cd super-fast-dumpster-diver

# Generate credentials
echo "CLICKHOUSE_PASSWORD=$(openssl rand -hex 16)" > .env
echo "CLICKHOUSE_USER=default" >> .env
echo "CLICKHOUSE_HOST=localhost" >> .env
echo "CLICKHOUSE_PORT=9000" >> .env

chmod +x *.py # Change permissions
#sudo apt update && sudo apt install uv -y # make sure you have python's uv installed

## Basic usage
# Start database (stored in ./ch_data), make sure it is running when using loader.py or searcher.py
docker compose up -d

# Index a directory (recursively)
./loader.py /path/to/scan --schema emails

# Search
./searcher.py --email example@example.com

# When you are done, stop database
docker compose down
```

---

## 🚀 Usage

### 1. Ingest Data (Incremental Indexing)
The loader scans directories, tracks changes, and only re-indexes modified files. How much this process takes varies a lot, but for example with a 7200RPM HDD + 8th gen i5, it can usually take \~1.5h per 100GB for files with a high concentration of matches (\~1B rows per 100GB) or 15-20m per 100GB for files with a low density of matches.

Pro tip: run `find /path/to/scan > /path/to/scan/paths.txt` if you want to index the filenames or folder names.

```bash
# If you are in macos, install ggrep
#brew install grep

# Index a directory (recursively)
./loader.py /path/to/scan --schema emails

# Resume/Update index (only processes new/modified/deleted files)
./loader.py /path/to/scan --schema emails

# Force re-indexing (only the indicated directory, recursively)
./loader.py /path/to/scan --schema emails --reindex

# Clean start (Drop DB)
./loader.py /path/to/scan --schema emails --clean
```

```bash
# To check all avaliable schemas (they are defined in config.py)
./searcher.py --help
usage: searcher.py [-h] [--limit LIMIT] [--left-offset LEFT_OFFSET] [--right-offset RIGHT_OFFSET] [--json]
                   [--email EMAILS_EMAIL] [--email-domain EMAILS_DOMAIN] [--email-domain-wildcard EMAILS_DOMAIN_WILDCARD]
                   [--user EMAILS_USER] [--user-wildcard EMAILS_USER_WILDCARD] [--domain DOMAINS_DOMAIN]
                   [--domain-wildcard DOMAINS_DOMAIN_WILDCARD] [--ip IPS_IP] [--ip-wildcard IPS_IP_WILDCARD]
                   [--uuid UUIDS_UUID] [--uuid-wildcard UUIDS_UUID_WILDCARD]

Search indexed data.

options:
  -h, --help            show this help message and exit
  --limit LIMIT         Limit results (Default: 10)
  --left-offset LEFT_OFFSET
  --right-offset RIGHT_OFFSET
  --json

Schema 'emails':
  --email EMAILS_EMAIL  Search for exact email
  --email-domain EMAILS_DOMAIN
                        Search for emails in domain
  --email-domain-wildcard EMAILS_DOMAIN_WILDCARD
                        Search for emails in domain wildcard (Uses LIKE syntax: % and _)
  --user EMAILS_USER    Search for emails by username (See README to improve performance)
  --user-wildcard EMAILS_USER_WILDCARD
                        Search for emails by username wildcard (Uses LIKE syntax; See README to improve performance)

Schema 'domains':
  --domain DOMAINS_DOMAIN
                        Search exact standalone domain (structure similar to a domain and is not part of an email
                        address).
  --domain-wildcard DOMAINS_DOMAIN_WILDCARD
                        Wildcard standalone domain search (Uses LIKE syntax; e.g. %.org or com.android.%)

Schema 'ips':
  --ip IPS_IP           Search exact IP
  --ip-wildcard IPS_IP_WILDCARD
                        Wildcard IP search (Uses LIKE syntax)

Schema 'uuids':
  --uuid UUIDS_UUID     Search UUID
  --uuid-wildcard UUIDS_UUID_WILDCARD
                        Wildcard UUID search (Uses LIKE syntax)
```

**Customizing Extraction:**
Edit `config.py` to define new Schemas (e.g., standalone domains, IPs, UUIDs) and their extraction commands.

### 2. Search

Note: searches are case sensitive.

**Emails:**
```bash
# Wildcards use LIKE syntax from SQL
./searcher.py --email lol@gmail.com
./searcher.py --email-domain example.com
./searcher.py --email-domain-wildcard '%.example.com' # % matches 0 or more characters
./searcher.py --user admin
./searcher.py --user-wildcard 'john_something' # _ is a single character wildcard
```

**Domains (Standalone):**
Search for domains appearing in URLs, source code, logs, etc. (ignoring those in email addresses).
```bash
./searcher.py --domain example.com
./searcher.py --domain-wildcard '%.example.com'
```

**IPs & UUIDs:**
```bash
./searcher.py --ip 1.2.3.4
./searcher.py --ip-wildcard '1.2.3.%'
./searcher.py --uuid 550e8400-e29b-41d4-a716-446655440000
./searcher.py --uuid-wildcard '550e8400-e29b-41d4-a716-%'
```

_Example:_
`./searcher.py --email lol@gmail.com`
```
Found 2 matches:

/path/to/scan/file1.txt (Offsets 297019840-297019853):
,XXXXXXX,XXXXXXXXXXX,X
XXXXXXX,XXXXXXXXXXX,XXXXXXXXXXXXXXXXXXXX,lol@gmail.com,XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
XXXXXXX,XXXXXXXXXXX,XXXXXXXXXXXXXXXXXXXX
----------------------------------------
/path/to/scan/dir/file2.txt (Offsets 2123879797-2123879810):
XXXXXXXXXXXXXXXXXXXXXX,1234567891234@gmail.com,XXXXXXXXXXXXXXXX,lol@gmail.com,XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
XXXXXXXXXXXXXXXXXXXXXXXXX
----------------------------------------
```

**Output JSON (for scripts/APIs):**
`./searcher.py --email lol@gmail.com --json`
```json
{"match": "lol@gmail.com", "file_path": "/path/to/scan/file1.txt", "offset": 297019840, "relative_offset": 64, "context": ",XXXXXXX,XXXXXXXXXXX,X\r\nXXXXXXX,XXXXXXXXXXX,XXXXXXXXXXXXXXXXXXXX,lol@gmail.com,XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX\r\nXXXXXXX,XXXXXXXXXXX,XXXXXXXXXXXXXXXXXXXX"}
{"match": "lol@gmail.com", "file_path": "/path/to/scan/dir/file2.txt", "offset": 2123879797, "relative_offset": 64, "context": "XXXXXXXXXXXXXXXXXXXXXX,1234567891234@gmail.com,XXXXXXXXXXXXXXXX,lol@gmail.com,XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX\nXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX\nXXXXXXXXXXXXXXXXXXXXXXXXX"}
```

---

## ⚡ Why it's fast

By using **ClickHouse** instead of traditional row-based databases (Postgres/MySQL), we achieve massive speed on consumer hardware:

| Feature | 🐢 Traditional DBs | 🐇 Dumpster Diver |
| :--- | :--- | :--- |
| **I/O Pattern** | Random Seeks (Slow) | Sequential Reads (Fast) |
| **Storage** | Row-Oriented | Column-Oriented (Reads only what it needs) |
| **Indexing** | B-Tree (Heavy) | Sparse Index (Fits in RAM) |
| **Performance** | Minutes | **500\~100ms (7200RPM HDD, <100ms if SSD) for 2B+ rows** |

---

## ⚙️ Hacker's Guide & Tuning

You can balance both worlds (speed/cost) by storing the index in a SSD and the raw data in a HDD.

The default email schema uses `ORDER BY (domain, user)`. This makes searching by **domain** (or exact email) instant ( $O(\log N)$ ).

### Customizing Performance
*   **Prioritize Users**: If you care more about finding a specific user (e.g., "admin") across all domains, change the order to `ORDER BY (user, domain)`. This will make user searches instant but domain searches slower.
*   **Have Disk Space?**: If you have space to spare, you don't have to choose! You can add a **ClickHouse Projection** (an extra sorted index) to index the data *both ways* (the emails index size will duplicate).
```bash
# Use the same credentials as the .env
curl -s -X POST http://default:password@localhost:8123 --data-binary "ALTER TABLE emails ADD PROJECTION user_order (SELECT * ORDER BY user, domain);"
# This launches a background process to apply the changes. If the database already has an index, in the worst case it may take almost as much time as the indexing process.
curl -s -X POST http://default:password@localhost:8123 --data-binary "ALTER TABLE emails MATERIALIZE PROJECTION user_order;"
# You can check if it is done with this command. Once finished, this will return an empty response.
curl -s -X POST http://default:password@localhost:8123 --data-binary "SELECT * FROM system.mutations WHERE is_done = 0;"
# It may take a while until changes are fully applied.
```

---

## ⚖️ Ethical Use

Super Fast Dumpster Diver is strictly intended for ethical research, security testing, and defense purposes only. We do not condone or support any malicious activity, unauthorized access, or actions violating laws or the rights of others.

By using this software, you agree to comply with all applicable laws and assume full responsibility for your actions. This code is provided "as-is" without any warranty, and the developers disclaim all liability for misuse or damage. Use at your own risk.

---

## 📝 License

MIT License. Hack away!
