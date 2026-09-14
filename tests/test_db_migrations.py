from sqlalchemy import create_engine, text

from app.db import init_db


def test_init_db_adds_v2_columns_to_existing_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.sqlite3'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE entries (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE extracted_records (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE reminders (id INTEGER PRIMARY KEY)"))

    init_db(engine)

    for table, expected in {
        "entries": {"revision", "deleted_at"},
        "extracted_records": {"deleted_at"},
        "reminders": {"deleted_at"},
    }.items():
        with engine.connect() as connection:
            columns = {
                row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
            }
        assert expected <= columns
