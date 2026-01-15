# 🗑️ Super Fast Dumpster Diver 🚀

**Simple. Hackable. Blazingly Fast.**

> "Finding a needle in a 2-billion-row haystack in milliseconds."

Super Fast Dumpster Diver is a minimalist tool to index and search massive unstructured plaintext (logs, dumps, archives, strings hidden deep in binary files). It's built on the **KISS** principle: no complex search engines, no manually parsing data, just smart use of ClickHouse columnar storage and random-access file seeks. It **runs instantly even on slow, spinning HDDs**.

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

## ⚡ Key Features

*   **Versatile**: Currently optimized for **emails**, but the pattern-matching loader can be easily tweaked for **URLs, IPs, UUIDs**, or any regex.
*   **Efficient**: The index typically consumes only **~20%** of the original raw data size.
*   **JSON Output**: Pipe-friendly JSON output for integration with other tools.
*   **Standard SQL**: The backend is just ClickHouse. You can query it with DBeaver, Grafana, or build your own API on top of it.

---

## ⚠️ Security Warning

**This tool is currently designed for local, trusted usage only.**

*   **No Input Sanitization**: The searcher constructs SQL queries directly. It is vulnerable to SQL Injection if exposed to untrusted input.
*   **Root Privileges**: The default Docker configuration runs as root.
*   **Do NOT expose** the database port (default credentials lol) or the searcher script to the public internet.

---

## ⚙️ Hacker's Guide & Tuning

The default schema uses `ORDER BY (domain, user)`. This makes searching by **domain** (or exact email) instant ($O(\log N)$).

### Customizing Performance
*   **Prioritize Users**: If you care more about finding a specific user (e.g., "admin") across all domains, change the order to `ORDER BY (user, domain)`. This will make user searches instant but domain searches slower.
*   **Have Disk Space?**: If you have space to spare, you don't have to choose! You can add a **ClickHouse Projection** (an extra sorted index) to index the data *both ways*.
    ```sql
    ALTER TABLE emails ADD PROJECTION user_order (SELECT * ORDER BY user, domain);
    ```

---

## 🚀 Usage

### 1. Setup
```bash
docker compose up -d
pip install tqdm  # Optional, for progress bars
```

### 2. Ingest Data (The "Dumpster Dive")
Pipe *anything* into the loader. The provided command uses `grep` to extract emails from raw files.

```bash
# Generate the scan command (optimized awk/grep pipeline)
echo "grep -r -b -o -P -a -i '[a-z0-9._%+-]{1,300}@[a-z0-9.-]{1,300}\.[a-z]{2,8}' /path/to/scan | \
awk -F: '\
{
    if (NF == 3) { f=\$1; o=\$2; m=\$3 } 
    else { m=\$NF; o=\$(NF-1); f=substr(\$0, 1, length(\$0)-length(o)-length(m)-2) }
    gsub(\"\\\"", \"\\\\\\\"\\\"", f)
    print \"\\\"" f "\\\",\" o \",\\\"" m "\\\"\""
}'" > scan.sh

# Run the loader
python3 loader.py --command "$(cat scan.sh)"
```

### 3. Search
**Instant Search (Hits Primary Key):**
```bash
python3 searcher.py --email user@example.com
python3 searcher.py --domain example.com
```

**Fast Username Search (Uses Bloom Filter):**
```bash
python3 searcher.py --user admin
```

**Output JSON (for scripts/APIs):**
```bash
python3 searcher.py --email user@gmail.com --json
```
_Output:_
```json
{"email": "user@gmail.com", "file_path": "/data/dump.txt", "offset_start": 1050, ...}
```

---

## 📝 License

MIT License. Hack away!
