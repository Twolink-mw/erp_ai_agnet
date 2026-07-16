"""MS-SQL 읽기 전용 커넥션.

DB 계정은 화이트리스트 뷰에 대한 SELECT 권한만 가진
전용 계정을 사용하는 것을 전제로 한다.
"""

import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        server = os.environ["MSSQL_SERVER"]
        database = os.environ["MSSQL_DATABASE"]
        user = os.environ["MSSQL_READONLY_USER"]
        password = os.environ["MSSQL_READONLY_PASSWORD"]
        driver = os.environ.get("MSSQL_ODBC_DRIVER", "ODBC Driver 18 for SQL Server")
        encrypt = os.environ.get("MSSQL_ENCRYPT", "yes")
        trust_server_cert = os.environ.get("MSSQL_TRUST_SERVER_CERTIFICATE", "no")

        # Include TrustServerCertificate when requested (useful for self-signed certs in test envs)
        conn_str = (
            f"mssql+pyodbc://{user}:{password}@{server}/{database}"
            f"?driver={driver.replace(' ', '+')}&Encrypt={encrypt}"
        )
        if trust_server_cert.lower() in ("1", "true", "yes", "y"):
            conn_str += "&TrustServerCertificate=yes"
        # 읽기 전용 워크로드: 커넥션 풀은 작게, 트랜잭션은 자동 커밋 없이 SELECT만 실행
        _engine = create_engine(conn_str, pool_size=5, pool_pre_ping=True)
    return _engine


def run_readonly_query(sql: str, max_rows: int = 1000) -> list[dict]:
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED"))
        result = conn.execute(text(sql))
        columns = list(result.keys())
        rows = result.fetchmany(max_rows)
        return [dict(zip(columns, row)) for row in rows]


def fetch_view_schema(schema: str, view: str) -> list[dict]:
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text(
                """
                SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :view
                ORDER BY ORDINAL_POSITION
                """
            ),
            {"schema": schema, "view": view},
        )
        return [dict(zip(result.keys(), row)) for row in result.fetchall()]
