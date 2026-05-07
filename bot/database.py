import sqlite3
import os

DB_PATH = os.getenv("DB_PATH", "/data/recipes.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dishes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                recipe TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ingredients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dish_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                amount TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'прочее',
                FOREIGN KEY (dish_id) REFERENCES dishes(id) ON DELETE CASCADE
            )
        """)
        conn.commit()


def add_dish(name: str, recipe: str, ingredients: list[dict]) -> int:
    """Add a dish with ingredients. Returns dish id."""
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO dishes (name, recipe) VALUES (?, ?)",
            (name, recipe)
        )
        dish_id = cursor.lastrowid
        conn.executemany(
            "INSERT INTO ingredients (dish_id, name, amount, category) VALUES (?, ?, ?, ?)",
            [(dish_id, ing["name"], ing["amount"], ing["category"]) for ing in ingredients]
        )
        conn.commit()
        return dish_id


def get_all_dishes() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT id, name FROM dishes ORDER BY name").fetchall()
        return [dict(r) for r in rows]


def get_dish_by_id(dish_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM dishes WHERE id = ?", (dish_id,)).fetchone()
        if not row:
            return None
        dish = dict(row)
        ings = conn.execute(
            "SELECT name, amount, category FROM ingredients WHERE dish_id = ? ORDER BY category, name",
            (dish_id,)
        ).fetchall()
        dish["ingredients"] = [dict(i) for i in ings]
        return dish


def get_ingredients_for_dishes(dish_ids: list[int]) -> list[dict]:
    """Get all ingredients for a list of dish ids."""
    placeholders = ",".join("?" * len(dish_ids))
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT i.name, i.amount, i.category, d.name as dish_name "
            f"FROM ingredients i JOIN dishes d ON i.dish_id = d.id "
            f"WHERE i.dish_id IN ({placeholders}) ORDER BY i.category, i.name",
            dish_ids
        ).fetchall()
        return [dict(r) for r in rows]


def delete_dish(dish_id: int) -> bool:
    with get_connection() as conn:
        result = conn.execute("DELETE FROM dishes WHERE id = ?", (dish_id,))
        conn.commit()
        return result.rowcount > 0


def dish_exists(name: str) -> bool:
    with get_connection() as conn:
        row = conn.execute("SELECT 1 FROM dishes WHERE LOWER(name) = LOWER(?)", (name,)).fetchone()
        return row is not None
