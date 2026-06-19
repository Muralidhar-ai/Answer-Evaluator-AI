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
    conn.commit()
    conn.close()

def save_evaluation(student_name, student_id, subject, total_max_marks, total_awarded_marks, questions_data):
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
        INSERT INTO evaluations (student_name, student_id, subject, total_max_marks, total_awarded_marks, questions_data)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (student_name, student_id, subject, total_max_marks, total_awarded_marks, questions_data))
    
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
        SELECT id, student_name, student_id, subject, total_max_marks, total_awarded_marks, timestamp
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
        SELECT id, student_name, student_id, subject, total_max_marks, total_awarded_marks, questions_data, timestamp
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
