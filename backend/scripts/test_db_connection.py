import os
import sys
from sqlalchemy import text

# 작업 디렉토리를 패키지 루트로 추가
sys.path.insert(0, '.')

try:
    from mcp_server import db
except Exception as e:
    print('IMPORT_ERROR', e)
    raise

required = [
    'MSSQL_SERVER',
    'MSSQL_DATABASE',
    'MSSQL_READONLY_USER',
    'MSSQL_READONLY_PASSWORD',
]
missing = [k for k in required if k not in os.environ]
if missing:
    print('MISSING_ENV_VARS', missing)
    sys.exit(2)

print('Found environment variables. Attempting DB connection...')
try:
    engine = db.get_engine()
    with engine.connect() as conn:
        # 간단한 쿼리로 접속 확인
        result = conn.execute(text('SELECT 1 AS ok'))
        row = result.fetchone()
        print('DB_OK:', row[0])
except Exception as e:
    print('DB_CONNECTION_ERROR', e)
    raise
