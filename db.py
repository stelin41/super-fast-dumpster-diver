from clickhouse_driver import Client
import config

def get_client():
    return Client(
        host=config.CLICKHOUSE_HOST,
        port=config.CLICKHOUSE_PORT,
        user=config.CLICKHOUSE_USER,
        password=config.CLICKHOUSE_PASSWORD,
        connect_timeout=10,
        # This allows the driver to handle external data streams better
        settings={'use_numpy': False}
    )

def run_query(query, params=None):
    client = get_client()
    try:
        # execute() handles both param substitution AND data insertion
        return client.execute(query, params)
    finally:
        client.disconnect()
