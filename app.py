import os
import uuid
import json
import traceback
import csv
import io
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, make_response
from config import Config
from utils.storage import init_db, save_evaluation, get_all_evaluations, get_evaluation_by_id, update_evaluation_marks
from utils.ocr import extract_questions_or_rubric, ocr_student_sheet
from utils.evaluator import align_answers, evaluate_all

app = Flask(__name__)
app.config.from_object(Config)

# Initialize database on startup
init_db()

# Helper function to get temp session file path
def get_temp_session_path(session_id):
    return os.path.join(app.config['UPLOAD_FOLDER'], f"session_{session_id}.json")

@app.route('/')
def index():
    return render_template('upload.html')

@app.route('/upload-ajax', methods=['POST'])
def upload_ajax():
    try:
        # Form details
        student_name = request.form.get('student_name', '').strip()
        student_id = request.form.get('student_id', '').strip()
        subject = request.form.get('subject', '').strip()

        if not student_name or not student_id or not subject:
            return jsonify({"status": "error", "message": "Missing student details (Name, ID, or Subject)."}), 400

        # Upload files and pasted text
        qp_file = request.files.get('question_paper_file')
        qp_text = request.form.get('question_paper_text', '').strip()
        
        ak_file = request.files.get('answer_key_file')
        ak_text = request.form.get('answer_key_text', '').strip()
        
        student_file = request.files.get('student_sheet_file')

        # Validation
        if not qp_text and (not qp_file or qp_file.filename == ''):
            return jsonify({"status": "error", "message": "Please provide a Question Paper (upload file or paste text)."}), 400
        if not ak_text and (not ak_file or ak_file.filename == ''):
            return jsonify({"status": "error", "message": "Please provide an Answer Key / Rubric (upload file or paste text)."}), 400
        if not student_file or student_file.filename == '':
            return jsonify({"status": "error", "message": "Please upload the Student's Answer Sheet."}), 400

        # Step-by-step progress logging (tracked in session or just done sequentially here)
        # Process Question Paper
        qp_questions = []
        if qp_text:
            qp_questions = extract_questions_or_rubric(paste_text=qp_text, is_rubric=False)
        else:
            qp_bytes = qp_file.read()
            qp_questions = extract_questions_or_rubric(file_bytes=qp_bytes, filename=qp_file.filename, is_rubric=False)

        # Process Answer Key
        ak_rubric = []
        if ak_text:
            ak_rubric = extract_questions_or_rubric(paste_text=ak_text, is_rubric=True)
        else:
            ak_bytes = ak_file.read()
            ak_rubric = extract_questions_or_rubric(file_bytes=ak_bytes, filename=ak_file.filename, is_rubric=True)

        # Process Student Answer Sheet (OCR)
        student_bytes = student_file.read()
        student_ocr_text = ocr_student_sheet(student_bytes, student_file.filename)

        # Align Answers
        aligned_questions = align_answers(qp_questions, ak_rubric, student_ocr_text)

        # Save to temp session cache file to avoid cookie limitations
        session_id = str(uuid.uuid4())
        temp_data = {
            "student_name": student_name,
            "student_id": student_id,
            "subject": subject,
            "aligned_questions": aligned_questions
        }
        
        temp_path = get_temp_session_path(session_id)
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(temp_data, f, ensure_ascii=False, indent=2)

        session['eval_session_id'] = session_id
        return jsonify({"status": "success", "session_id": session_id})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Processing failed: {str(e)}"}), 500

@app.route('/preview')
def preview():
    session_id = request.args.get('session_id') or session.get('eval_session_id')
    if not session_id:
        return redirect(url_for('index'))
    
    temp_path = get_temp_session_path(session_id)
    if not os.path.exists(temp_path):
        return redirect(url_for('index'))
        
    try:
        with open(temp_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return f"Error loading preview data: {str(e)}", 500

    return render_template(
        'preview.html', 
        session_id=session_id,
        student_name=data.get("student_name"),
        student_id=data.get("student_id"),
        subject=data.get("subject"),
        questions=data.get("aligned_questions", [])
    )

@app.route('/evaluate', methods=['POST'])
def evaluate():
    session_id = request.form.get('session_id')
    if not session_id:
        return "Session expired or missing.", 400

    temp_path = get_temp_session_path(session_id)
    if not os.path.exists(temp_path):
        return "Extraction session not found. Please upload again.", 404

    try:
        with open(temp_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Retrieve edits from post form
        aligned_questions = data.get("aligned_questions", [])
        updated_questions = []

        for idx, q in enumerate(aligned_questions):
            q_no = q.get("question_no")
            # Parse edited marks
            max_marks_str = request.form.get(f"max_marks_{idx}", "").strip()
            max_marks = float(max_marks_str) if max_marks_str else 0.0
            
            # Parse edited question text
            q_text = request.form.get(f"question_text_{idx}", "").strip()
            
            # Parse edited rubric points
            rubric_str = request.form.get(f"rubric_points_{idx}", "").strip()
            rubric_points = [p.strip() for p in rubric_str.split("\n") if p.strip()]
            
            # Parse edited student answer
            student_answer = request.form.get(f"student_answer_{idx}", "").strip()

            updated_questions.append({
                "question_no": q_no,
                "question_text": q_text,
                "max_marks": max_marks,
                "rubric_points": rubric_points,
                "student_answer": student_answer
            })

        # Run evaluation engine
        evaluation_results = evaluate_all(updated_questions)

        # Save to SQLite database
        eval_id = save_evaluation(
            student_name=data.get("student_name"),
            student_id=data.get("student_id"),
            subject=data.get("subject"),
            total_max_marks=evaluation_results["total_max_marks"],
            total_awarded_marks=evaluation_results["total_awarded_marks"],
            questions_data=evaluation_results["questions"]
        )

        # Clean up temp file
        try:
            os.remove(temp_path)
        except OSError:
            pass

        # Clear session
        session.pop('eval_session_id', None)

        return redirect(url_for('results', eval_id=eval_id))

    except Exception as e:
        traceback.print_exc()
        return f"Evaluation process failed: {str(e)}", 500

@app.route('/results/<int:eval_id>')
def results(eval_id):
    eval_data = get_evaluation_by_id(eval_id)
    if not eval_data:
        return "Evaluation not found.", 404
        
    return render_template('results.html', eval=eval_data)

@app.route('/update-marks/<int:eval_id>', methods=['POST'])
def update_marks(eval_id):
    try:
        eval_data = get_evaluation_by_id(eval_id)
        if not eval_data:
            return jsonify({"status": "error", "message": "Evaluation not found."}), 404

        questions = eval_data.get("questions_data", [])
        new_total_awarded = 0.0

        for idx, q in enumerate(questions):
            override_val = request.form.get(f"override_marks_{idx}")
            if override_val is not None:
                try:
                    override_marks = float(override_val)
                    max_marks = float(q.get("max_marks", 0))
                    # Bound between 0 and max marks
                    override_marks = max(0.0, min(override_marks, max_marks))
                    q["awarded_marks"] = override_marks
                except ValueError:
                    pass
            new_total_awarded += q.get("awarded_marks", 0.0)

        # Update database
        update_evaluation_marks(eval_id, questions, new_total_awarded)
        return jsonify({"status": "success", "new_total": new_total_awarded})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/history')
def history():
    evals = get_all_evaluations()
    return render_template('history.html', evaluations=evals)

@app.route('/export-csv/<int:eval_id>')
def export_csv(eval_id):
    try:
        eval_data = get_evaluation_by_id(eval_id)
        if not eval_data:
            return "Evaluation not found.", 404
            
        dest = io.StringIO()
        writer = csv.writer(dest)
        
        # Metadata
        writer.writerow(["AI Answer Sheet Evaluation Report"])
        writer.writerow([])
        writer.writerow(["Student Name", eval_data.get("student_name")])
        writer.writerow(["Student ID", eval_data.get("student_id")])
        writer.writerow(["Subject", eval_data.get("subject")])
        writer.writerow(["Timestamp", eval_data.get("timestamp")])
        writer.writerow(["Total Max Marks", eval_data.get("total_max_marks")])
        writer.writerow(["Total Awarded Marks", eval_data.get("total_awarded_marks")])
        writer.writerow([])
        
        # Details headers
        writer.writerow(["Question No", "Question Text", "Max Marks", "Awarded Marks", "Confidence", "Matched Points", "Missing Points", "Feedback"])
        
        for q in eval_data.get("questions_data", []):
            matched = "; ".join(q.get("matched_points", []))
            missing = "; ".join(q.get("missing_points", []))
            writer.writerow([
                q.get("question_no"),
                q.get("question_text"),
                q.get("max_marks"),
                q.get("awarded_marks"),
                q.get("confidence"),
                matched,
                missing,
                q.get("feedback")
            ])
            
        output = make_response(dest.getvalue())
        output.headers["Content-Disposition"] = f"attachment; filename=evaluation_{eval_data.get('student_id')}_{eval_id}.csv"
        output.headers["Content-type"] = "text/csv"
        return output
    except Exception as e:
        traceback.print_exc()
        return f"Failed to generate CSV: {str(e)}", 500

@app.route('/export-history-csv')
def export_history_csv():
    try:
        evals = get_all_evaluations()
        dest = io.StringIO()
        writer = csv.writer(dest)
        
        writer.writerow(["Evaluation ID", "Student Name", "Student ID", "Subject", "Total Max Marks", "Total Awarded Marks", "Timestamp"])
        for row in evals:
            writer.writerow([
                row.get("id"),
                row.get("student_name"),
                row.get("student_id"),
                row.get("subject"),
                row.get("total_max_marks"),
                row.get("total_awarded_marks"),
                row.get("timestamp")
            ])
            
        output = make_response(dest.getvalue())
        output.headers["Content-Disposition"] = "attachment; filename=evaluation_history.csv"
        output.headers["Content-type"] = "text/csv"
        return output
    except Exception as e:
        traceback.print_exc()
        return f"Failed to generate history CSV: {str(e)}", 500

if __name__ == '__main__':
    # Bind to 0.0.0.0 for Render deployments, port loaded from config or default 5000
    port = int(os.getenv("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
