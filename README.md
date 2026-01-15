# 🗑️ Super Fast Dumpster Diver 🚀

**Simple. Hackable. Blazingly Fast.**

> "Finding a needle in a 2-billion-row haystack in an instant."

Super Fast Dumpster Diver is a minimalist tool to index and search specific patterns inside the **contents** of massive unstructured plaintext files (logs, dumps, archives, binaries) across a directory tree. It provides **instant search** on typical hardware, performing exceptionally well even on slow, spinning HDDs.

While currently designed for **cybersecurity intelligence and recon gathering**, its simple and hackable nature makes it easy to adapt for other use cases like searching massive codebases. It is designed for easy integration with other software and APIs.

### 🎯 Key Advantages
*   **Blazingly Fast**: Instant searches even in billions of rows.
*   **Space Efficient**: Uses significantly less disk space for indexes than traditional solutions like **Recoll** (typically ~20% of raw data size).
*   **Hardware Friendly**: Optimized for sequential I/O; runs great on standard HDDs.
*   **Hackable**: Built on the KISS principle—smart use of ClickHouse and a few Python scripts.

---

## ⚡ Key Features

*   **Versatile**: Currently optimized for **emails**, but the pattern-matching loader can be easily tweaked for **standalone domains (URLs, code, logs), IPs, UUIDs**, or any regex.
*   **Efficient**: The index typically consumes up to **~20%** of the original raw data size per regex indexed.
*   **JSON Output**: Pipe-friendly JSON output for integration with other tools.
*   **Standard SQL**: The backend is just ClickHouse. You can query it with DBeaver, Grafana, or build your own API on top of it.

---

## ⚠️ Security Warning

**This tool is currently designed for local, trusted usage only.**

*   **No Input Sanitization**: The searcher constructs SQL queries directly. It is vulnerable to SQL Injection if exposed to untrusted input.
*   **Root Privileges**: The default Docker configuration runs as root.
*   **Do NOT expose** the searcher script to the public internet.

---

## 🚀 Usage

### 1. Setup

**Generate credentials:**
```bash
# Generate random password in .env
echo "CLICKHOUSE_PASSWORD=$(openssl rand -base64 12)" > .env
echo "CLICKHOUSE_USER=default" >> .env
echo "CLICKHOUSE_HOST=localhost" >> .env
echo "CLICKHOUSE_PORT=8123" >> .env
```

**Start the Database:**
```bash
docker compose up -d
pip install tqdm  # Optional, for progress bars
```

### 2. Ingest Data (Incremental Indexing)
The loader scans directories, tracks changes, and only re-indexes modified files. How much this process takes varies a lot, but for example with a 7200RPM HDD + 8th gen i5, it can usually take 1-1.5h per 100GB for files with a high concentration of matches (\~1B rows per 100GB) or 15-20m per 100GB for files with a low density of matches.

Pro tip: run `find /path/to/scan > /path/to/scan/paths.txt` if you want to index the filenames or folder names.

```bash
# To check all avaliable schemas, they are defined in config.py
python3 searcher.py --help
usage: searcher.py [-h] [--limit LIMIT] [--left-offset LEFT_OFFSET] [--right-offset RIGHT_OFFSET] [--json] [--email EMAILS_EMAIL] [--email-domain EMAILS_DOMAIN]
                   [--email-domain-wildcard EMAILS_DOMAIN_WILDCARD] [--user EMAILS_USER] [--domain DOMAINS_DOMAIN] [--domain-wildcard DOMAINS_DOMAIN_WILDCARD]
                   [--ip IPS_IP] [--uuid UUIDS_UUID]

Search indexed data.

optional arguments:
  -h, --help            show this help message and exit
  --limit LIMIT         Max number of results (default: 10)
  --left-offset LEFT_OFFSET
                        Bytes to read before the match
  --right-offset RIGHT_OFFSET
                        Bytes to read after the match
  --json                Output results as JSON

Schema 'emails':
  --email EMAILS_EMAIL  Search for exact email
  --email-domain EMAILS_DOMAIN
                        Search for emails in domain
  --email-domain-wildcard EMAILS_DOMAIN_WILDCARD
                        Search for emails in domain with wildcard (e.g. *.com)
  --user EMAILS_USER    Search for emails by username (slow)

Schema 'domains':
  --domain DOMAINS_DOMAIN
                        Search for exact *standalone* domain (anything that is not part of an email address)
  --domain-wildcard DOMAINS_DOMAIN_WILDCARD
                        Search for *standalone* domain with wildcard (e.g. *.org)

Schema 'ips':
  --ip IPS_IP           Search for exact IP

Schema 'uuids':
  --uuid UUIDS_UUID     Search for UUID
```

```bash
# Index a directory (recursively)
python3 loader.py /path/to/scan --schema emails

# Resume/Update index (only processes new/modified files)
python3 loader.py /path/to/scan --schema emails

# Force re-index everything
python3 loader.py /path/to/scan --schema emails --reindex

# Clean start (Drop DB)
python3 loader.py /path/to/scan --schema emails --clean
```

**Customizing Extraction:**
Edit `config.py` to define new Schemas (e.g., standalone domains, IPs, UUIDs) and their extraction commands.

### 3. Search
**Emails:**
```bash
python3 searcher.py --email lol@gmail.com
python3 searcher.py --email-domain example.com
python3 searcher.py --email-domain-wildcard '*.example.com'
python3 searcher.py --user admin
```

**Domains (Standalone):**
Search for domains appearing in URLs, source code, logs, etc. (ignoring those in email addresses).
```bash
python3 searcher.py --domain example.com
python3 searcher.py --domain-wildcard '*.example.com'
```

**IPs & UUIDs:**
```bash
python3 searcher.py --ip 1.2.3.4
python3 searcher.py --uuid 550e8400-e29b-41d4-a716-446655440000
```

_Output:_
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

**Username Search (Uses Bloom Filter):**
```bash
python3 searcher.py --user admin
```

**Output JSON (for scripts/APIs):**
```bash
python3 searcher.py --email lol@gmail.com --json
```
_Output:_
```json
{"email": "lol@gmail.com", "file_path": "/path/to/scan/file1.txt", "offset_start": 297019840, "offset_end": 297019853, "left_offset": 64, "right_offset": 128, "context": ",XXXXXXX,XXXXXXXXXXX,X\r\nXXXXXXX,XXXXXXXXXXX,XXXXXXXXXXXXXXXXXXXX,lol@gmail.com,XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX\r\nXXXXXXX,XXXXXXXXXXX,XXXXXXXXXXXXXXXXXXXX"}
{"email": "lol@gmail.com", "file_path": "/path/to/scan/dir/file2.txt", "offset_start": 2123879797, "offset_end": 2123879810, "left_offset": 64, "right_offset": 128, "context": "XXXXXXXXXXXXXXXXXXXXXX,1234567891234@gmail.com,XXXXXXXXXXXXXXXX,lol@gmail.com,XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX\nXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX\nXXXXXXXXXXXXXXXXXXXXXXXXX"}
```

---

## ⚡ Why it's fast

By using **ClickHouse** instead of traditional row-based databases (Postgres/MySQL), we achieve massive speed on consumer hardware:

| Feature | 🐢 Traditional DBs | 🐇 Dumpster Diver |
| :--- | :--- | :--- |
| **I/O Pattern** | Random Seeks (Slow) | Sequential Reads (Fast) |
| **Storage** | Row-Oriented | Column-Oriented (Reads only what it needs) |
| **Indexing** | B-Tree (Heavy) | Sparse Index (Fits in RAM) |
| **Performance** | Seconds/Minutes | **~130ms for 2B+ rows** (on a 7200RPM HDD) |

---

## ⚙️ Hacker's Guide & Tuning

The default email schema uses `ORDER BY (domain, user)`. This makes searching by **domain** (or exact email) instant ($O(\log N)$).

### Customizing Performance
*   **Prioritize Users**: If you care more about finding a specific user (e.g., "admin") across all domains, change the order to `ORDER BY (user, domain)`. This will make user searches instant but domain searches slower.
*   **Have Disk Space?**: If you have space to spare, you don't have to choose! You can add a **ClickHouse Projection** (an extra sorted index) to index the data *both ways*.
    ```sql
    ALTER TABLE emails ADD PROJECTION user_order (SELECT * ORDER BY user, domain);
    ```

---

Expect more updates soon™️

## 📝 License

MIT License. Hack away!
