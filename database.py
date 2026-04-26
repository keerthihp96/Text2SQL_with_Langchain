# database.py

import os
import snowflake.connector
from dotenv import load_dotenv

load_dotenv()


def get_connection():
    """Establish Snowflake connection using env variables."""
    return snowflake.connector.connect(
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA")
    )


def execute_query(sql: str):
    """
    Execute SQL on Snowflake.
    Returns: (columns, rows, error)
    """
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(sql)
        rows    = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return columns, rows, None

    except Exception as e:
        return None, None, str(e)

    finally:
        if conn:
            conn.close()


def test_connection():
    """Test Snowflake connection."""
    try:
        conn = get_connection()
        conn.close()
        return True, "Connection successful"
    except Exception as e:
        return False, str(e)