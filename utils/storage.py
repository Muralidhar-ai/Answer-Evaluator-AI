import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evaluations.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_name TEXT NOT NULL,
            student_id TEXT NOT NULL,
            subject TEXT NOT NULL,
            total_max_marks REAL NOT NULL,
            total_awarded_marks REAL NOT NULL,
            questions_data TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bulk_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            student_count INTEGER NOT NULL,
            evaluation_ids TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Run inline migrations to add total_marks and pass_marks to tables if missing
    import sqlite3
    try:
        cursor.execute("ALTER TABLE evaluations ADD COLUMN total_marks REAL DEFAULT 0.0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE evaluations ADD COLUMN pass_marks REAL DEFAULT 0.0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE bulk_evaluations ADD COLUMN total_marks REAL DEFAULT 0.0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE bulk_evaluations ADD COLUMN pass_marks REAL DEFAULT 0.0")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

def save_evaluation(student_name, student_id, subject, total_max_marks, total_awarded_marks, questions_data, total_marks=0.0, pass_marks=0.0):
    """
    Saves a new evaluation session.
    questions_data should be a list of dicts serialized to JSON.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Serialize questions_data if it is a list/dict
    if not isinstance(questions_data, str):
        questions_data = json.dumps(questions_data)
        
    cursor.execute("""
        INSERT INTO evaluations (student_name, student_id, subject, total_max_marks, total_awarded_marks, questions_data, total_marks, pass_marks)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (student_name, student_id, subject, total_max_marks, total_awarded_marks, questions_data, total_marks, pass_marks))
    
    eval_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return eval_id

def get_all_evaluations():
    """
    Retrieves all past evaluations, sorted by newest first.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, student_name, student_id, subject, total_max_marks, total_awarded_marks, timestamp, total_marks, pass_marks
        FROM evaluations
        ORDER BY timestamp DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_evaluation_by_id(eval_id):
    """
    Retrieves a single evaluation session by ID, parsing questions_data back to a list of dicts.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, student_name, student_id, subject, total_max_marks, total_awarded_marks, questions_data, timestamp, total_marks, pass_marks
        FROM evaluations
        WHERE id = ?
    """, (eval_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        eval_dict = dict(row)
        eval_dict["questions_data"] = json.loads(eval_dict["questions_data"])
        return eval_dict
    return None

def update_evaluation_marks(eval_id, questions_data, new_total_awarded):
    """
    Updates the evaluation data and total awarded marks (for manual override).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if not isinstance(questions_data, str):
        questions_data = json.dumps(questions_data)
        
    cursor.execute("""
        UPDATE evaluations
        SET questions_data = ?, total_awarded_marks = ?
        WHERE id = ?
    """, (questions_data, new_total_awarded, eval_id))
    
    conn.commit()
    conn.close()
    return True

def save_bulk_evaluation(subject, student_count, evaluation_ids, total_marks=0.0, pass_marks=0.0):
    """
    Saves a new bulk evaluation session.
    evaluation_ids should be a list of ints serialized to JSON.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if not isinstance(evaluation_ids, str):
        evaluation_ids = json.dumps(evaluation_ids)
        
    cursor.execute("""
        INSERT INTO bulk_evaluations (subject, student_count, evaluation_ids, total_marks, pass_marks)
        VALUES (?, ?, ?, ?, ?)
    """, (subject, student_count, evaluation_ids, total_marks, pass_marks))
    
    bulk_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return bulk_id

def get_all_bulk_evaluations():
    """
    Retrieves all past bulk evaluations, sorted by newest first.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, subject, student_count, evaluation_ids, timestamp, total_marks, pass_marks
        FROM bulk_evaluations
        ORDER BY timestamp DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_bulk_evaluation_by_id(bulk_id):
    """
    Retrieves a single bulk evaluation by ID.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, subject, student_count, evaluation_ids, timestamp, total_marks, pass_marks
        FROM bulk_evaluations
        WHERE id = ?
    """, (bulk_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        bulk_dict = dict(row)
        bulk_dict["evaluation_ids"] = json.loads(bulk_dict["evaluation_ids"])
        return bulk_dict
    return None

def delete_evaluation(eval_id):
    """
    Deletes a single evaluation record by ID.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM evaluations WHERE id = ?", (eval_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def delete_bulk_evaluation(bulk_id):
    """
    Deletes a bulk evaluation session by ID.
    Individual student evaluations are kept in history.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bulk_evaluations WHERE id = ?", (bulk_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0
