import os
import uuid
import json
import traceback
import csv
import io
import threading
import zipfile
import re
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, make_response, send_file
from openpyxl import Workbook
from config import Config
from utils.storage import (
    init_db, save_evaluation, get_all_evaluations, get_evaluation_by_id, 
    update_evaluation_marks, save_bulk_evaluation, get_all_bulk_evaluations, 
    get_bulk_evaluation_by_id, delete_evaluation, delete_bulk_evaluation
)
from utils.ocr import extract_questions_or_rubric, ocr_student_sheet
from utils.evaluator import align_answers, evaluate_all


app = Flask(__name__)
app.config.from_object(Config)

# Initialize database on startup
init_db()

# Helper function to get temp session file path
def get_temp_session_path(session_id):
    return os.path.join(app.config['UPLOAD_FOLDER'], f"session_{session_id}.json")

# ----------------------------------------------------
# Bulk Class Evaluation Background Processor State & Logic
# ----------------------------------------------------
bulk_jobs = {}

def parse_student_filename(filename):
    """
    Extracts student name and roll number from the filename:
    'Name_RollNo.pdf' -> Name, RollNo
    """
    base_name = os.path.splitext(os.path.basename(filename))[0]
    parts = base_name.split('_')
    if len(parts) >= 2:
        name = "_".join(parts[:-1]).strip()
        roll_no = parts[-1].strip()
        return name, roll_no
    return base_name.strip() or "Unknown", "Unknown"

def run_bulk_evaluation_thread(session_id, qp_questions, ak_rubric, subject, files_to_process, total_marks_config=0.0, pass_marks_config=0.0, pass_percentage_config=0.0):
    job = bulk_jobs.get(session_id)
    if not job:
        return
        
    evaluation_ids = []
    final_total_marks = total_marks_config
    final_pass_marks = pass_marks_config
    
    for idx, (filename, file_bytes) in enumerate(files_to_process):
        name, roll_no = parse_student_filename(filename)
        
        # Update progress status
        job["current"] = idx + 1
        job["current_student"] = f"{name} ({roll_no})"
        
        try:
            # 1. OCR raw student sheet
            student_ocr_text = ocr_student_sheet(file_bytes, filename)
            
            # 2. Align answers
            aligned_questions = align_answers(qp_questions, ak_rubric, student_ocr_text)
            
            # 3. Evaluate answers
            evaluation_results = evaluate_all(aligned_questions)
            
            # Compute total and pass marks configs per student run
            total_marks = total_marks_config if total_marks_config > 0 else evaluation_results["total_max_marks"]
            if pass_percentage_config > 0:
                pass_marks = (pass_percentage_config / 100.0) * total_marks
            else:
                pass_marks = pass_marks_config
                
            final_total_marks = total_marks
            final_pass_marks = pass_marks
            
            # 4. Save evaluation
            eval_id = save_evaluation(
                student_name=name,
                student_id=roll_no,
                subject=subject,
                total_max_marks=evaluation_results["total_max_marks"],
                total_awarded_marks=evaluation_results["total_awarded_marks"],
                questions_data=evaluation_results["questions"],
                total_marks=total_marks,
                pass_marks=pass_marks
            )
            evaluation_ids.append(eval_id)
            job["results"].append({
                "name": name,
                "roll_no": roll_no,
                "eval_id": eval_id,
                "status": "success",
                "total_score": evaluation_results["total_awarded_marks"],
                "max_total": evaluation_results["total_max_marks"],
                "needs_review": any(q.get("needs_manual_review", False) for q in evaluation_results["questions"])
            })
        except Exception as e:
            tb_str = traceback.format_exc()
            print(f"Error processing student file {filename}: {str(e)}\n{tb_str}")
            job["errors"].append({
                "filename": filename,
                "name": name,
                "roll_no": roll_no,
                "error": str(e)
            })
            job["results"].append({
                "name": name,
                "roll_no": roll_no,
                "status": "failed",
                "error": str(e)
            })
            
    # Save bulk session in storage
    if evaluation_ids:
        try:
            bulk_id = save_bulk_evaluation(
                subject=subject,
                student_count=len(evaluation_ids),
                evaluation_ids=evaluation_ids,
                total_marks=final_total_marks,
                pass_marks=final_pass_marks
            )
            job["bulk_id"] = bulk_id
            job["status"] = "completed"
        except Exception as e:
            print(f"Error saving bulk session to DB: {str(e)}")
            job["status"] = "failed"
            job["global_error"] = f"Failed to save bulk evaluation session to database: {str(e)}"
    else:
        job["status"] = "failed"
        job["global_error"] = "All student answer sheets in this batch failed to process."

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

        # Get total_marks and pass_marks from form
        total_marks_str = request.form.get('total_marks', '').strip()
        pass_marks_str = request.form.get('pass_marks', '').strip()
        
        try:
            total_marks = float(total_marks_str) if total_marks_str else evaluation_results["total_max_marks"]
        except ValueError:
            total_marks = evaluation_results["total_max_marks"]
            
        try:
            pass_marks = float(pass_marks_str) if pass_marks_str else 0.0
        except ValueError:
            pass_marks = 0.0

        # Save to SQLite database
        eval_id = save_evaluation(
            student_name=data.get("student_name"),
            student_id=data.get("student_id"),
            subject=data.get("subject"),
            total_max_marks=evaluation_results["total_max_marks"],
            total_awarded_marks=evaluation_results["total_awarded_marks"],
            questions_data=evaluation_results["questions"],
            total_marks=total_marks,
            pass_marks=pass_marks
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
    
    # Calculate global needs_manual_review flag dynamically
    eval_data["needs_manual_review"] = any(
        q.get("needs_manual_review", False) for q in eval_data.get("questions_data", [])
    )
        
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
                    q["final_awarded_marks"] = override_marks
                    q["needs_manual_review"] = False
                except ValueError:
                    pass
            new_total_awarded += q.get("final_awarded_marks", q.get("awarded_marks", 0.0))

        # Update database
        update_evaluation_marks(eval_id, questions, new_total_awarded)
        return jsonify({"status": "success", "new_total": new_total_awarded})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/history')
def history():
    evals = get_all_evaluations()
    bulk_evals = get_all_bulk_evaluations()
    return render_template('history.html', evaluations=evals, bulk_evaluations=bulk_evals)

@app.route('/delete-evaluation/<int:eval_id>', methods=['POST'])
def delete_evaluation_route(eval_id):
    try:
        success = delete_evaluation(eval_id)
        if success:
            return jsonify({"status": "success", "message": "Evaluation deleted."})
        return jsonify({"status": "error", "message": "Evaluation not found."}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/delete-bulk/<int:bulk_id>', methods=['POST'])
def delete_bulk_route(bulk_id):
    try:
        success = delete_bulk_evaluation(bulk_id)
        if success:
            return jsonify({"status": "success", "message": "Bulk session deleted."})
        return jsonify({"status": "error", "message": "Bulk session not found."}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/bulk')
def bulk():
    return render_template('bulk_upload.html')

@app.route('/bulk-upload-ajax', methods=['POST'])
def bulk_upload_ajax():
    try:
        subject = request.form.get('subject', '').strip()
        if not subject:
            return jsonify({"status": "error", "message": "Missing subject name."}), 400

        # Upload files and pasted text
        qp_file = request.files.get('question_paper_file')
        qp_text = request.form.get('question_paper_text', '').strip()
        
        ak_file = request.files.get('answer_key_file')
        ak_text = request.form.get('answer_key_text', '').strip()

        # Validation
        if not qp_text and (not qp_file or qp_file.filename == ''):
            return jsonify({"status": "error", "message": "Please provide a Question Paper."}), 400
        if not ak_text and (not ak_file or ak_file.filename == ''):
            return jsonify({"status": "error", "message": "Please provide an Answer Key / Rubric."}), 400

        # Extract Question Paper & Answer Key rubrics ONCE
        qp_questions = []
        if qp_text:
            qp_questions = extract_questions_or_rubric(paste_text=qp_text, is_rubric=False)
        else:
            qp_bytes = qp_file.read()
            qp_questions = extract_questions_or_rubric(file_bytes=qp_bytes, filename=qp_file.filename, is_rubric=False)

        ak_rubric = []
        if ak_text:
            ak_rubric = extract_questions_or_rubric(paste_text=ak_text, is_rubric=True)
        else:
            ak_bytes = ak_file.read()
            ak_rubric = extract_questions_or_rubric(file_bytes=ak_bytes, filename=ak_file.filename, is_rubric=True)

        # Parse uploaded answer sheets (ZIP and/or list of files)
        files_to_process = []
        zip_file = request.files.get('student_sheets_zip')
        
        if zip_file and zip_file.filename.endswith('.zip'):
            zip_bytes = zip_file.read()
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                for info in zf.infolist():
                    if info.is_dir() or '__MACOSX' in info.filename:
                        continue
                    ext = os.path.splitext(info.filename)[1].lower()
                    if ext in ['.pdf', '.png', '.jpg', '.jpeg', '.webp']:
                        files_to_process.append((os.path.basename(info.filename), zf.read(info.filename)))
        else:
            uploaded_files = request.files.getlist('student_sheets_files')
            for f in uploaded_files:
                if f and f.filename:
                    files_to_process.append((f.filename, f.read()))

        if not files_to_process:
            return jsonify({"status": "error", "message": "Please upload a ZIP file or multiple student answer sheets."}), 400

        # Read pass/fail config
        total_marks_str = request.form.get('total_marks', '').strip()
        pass_marks_str = request.form.get('pass_marks', '').strip()
        pass_percentage_str = request.form.get('pass_percentage', '').strip()
        use_percentage = request.form.get('use_percentage') == 'true' or request.form.get('use_percentage') == 'on'

        total_marks_config = 0.0
        if total_marks_str:
            try:
                total_marks_config = float(total_marks_str)
            except ValueError:
                pass
                
        pass_marks_config = 0.0
        if pass_marks_str and not use_percentage:
            try:
                pass_marks_config = float(pass_marks_str)
            except ValueError:
                pass
                
        pass_percentage_config = 0.0
        if use_percentage and pass_percentage_str:
            try:
                pass_percentage_config = float(pass_percentage_str)
            except ValueError:
                pass

        # Create session state
        session_id = str(uuid.uuid4())
        bulk_jobs[session_id] = {
            "status": "running",
            "current": 0,
            "total": len(files_to_process),
            "current_student": "Initializing...",
            "results": [],
            "errors": [],
            "bulk_id": None
        }

        # Start sequential evaluation in background thread
        t = threading.Thread(
            target=run_bulk_evaluation_thread,
            args=(session_id, qp_questions, ak_rubric, subject, files_to_process, total_marks_config, pass_marks_config, pass_percentage_config)
        )
        t.daemon = True
        t.start()

        return jsonify({"status": "success", "session_id": session_id})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Bulk initialization failed: {str(e)}"}), 500

@app.route('/bulk-status/<session_id>')
def bulk_status(session_id):
    job = bulk_jobs.get(session_id)
    if not job:
        return jsonify({"status": "error", "message": "Job session not found."}), 404
    return jsonify(job)

@app.route('/bulk-results/<int:bulk_id>')
def bulk_results(bulk_id):
    bulk_data = get_bulk_evaluation_by_id(bulk_id)
    if not bulk_data:
        return "Bulk evaluation session not found.", 404
        
    students = []
    for eval_id in bulk_data["evaluation_ids"]:
        eval_dict = get_evaluation_by_id(eval_id)
        if eval_dict:
            # Check if student needs manual review (flagged)
            eval_dict["needs_manual_review"] = any(
                q.get("needs_manual_review", False) for q in eval_dict.get("questions_data", [])
            )
            students.append(eval_dict)
            
    return render_template('bulk_results.html', bulk=bulk_data, students=students)

@app.route('/export-excel/<int:bulk_id>')
def export_excel(bulk_id):
    bulk_data = get_bulk_evaluation_by_id(bulk_id)
    if not bulk_data:
        return "Bulk session not found.", 404
        
    students = []
    for eval_id in bulk_data["evaluation_ids"]:
        eval_dict = get_evaluation_by_id(eval_id)
        if eval_dict:
            students.append(eval_dict)
            
    if not students:
        return "No student records found in this bulk session.", 404

    # Create excel workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Class Summary"

    # Identify all question numbers from student data
    question_numbers = []
    for s in students:
        for q in s.get("questions_data", []):
            q_no = str(q.get("question_no", ""))
            if q_no and q_no not in question_numbers:
                question_numbers.append(q_no)

    try:
        question_numbers.sort(key=lambda x: [int(s) if s.isdigit() else s for s in re.split(r'(\d+)', x)])
    except Exception:
        question_numbers.sort()

    # Headers
    headers = ["Student Name", "Roll No"]
    for q_no in question_numbers:
        headers.append(f"Q{q_no} Marks")
    headers.extend(["Total Score", "Max Marks", "Status", "Flagged for Review"])
    ws.append(headers)

    # Rows
    for s in students:
        row = [s.get("student_name"), s.get("student_id")]
        
        # Pull marks for each question
        for q_no in question_numbers:
            val = ""
            for q in s.get("questions_data", []):
                if str(q.get("question_no", "")) == q_no:
                    val = q.get("final_awarded_marks", q.get("awarded_marks", 0.0))
                    break
            row.append(val)
            
        # Overall status
        flagged = "No"
        for q in s.get("questions_data", []):
            if q.get("needs_manual_review"):
                flagged = "Yes"
                break
                
        total_awarded = s.get("total_awarded_marks", 0.0)
        student_pass_marks = s.get("pass_marks", 0.0)
        status = "PASS" if total_awarded >= student_pass_marks else "FAIL"

        row.extend([
            s.get("total_awarded_marks"),
            s.get("total_max_marks"),
            status,
            flagged
        ])
        ws.append(row)

    ws.append([]) # Spacer row
    
    # Calculate overall metrics
    total_students = len(students)
    passed_count = sum(1 for s in students if s.get("total_awarded_marks", 0.0) >= s.get("pass_marks", 0.0))
    pass_rate_pct = (passed_count / total_students * 100.0) if total_students > 0 else 0.0
    
    bulk_total_marks = bulk_data.get("total_marks", 0.0)
    bulk_pass_marks = bulk_data.get("pass_marks", 0.0)
    
    ws.append(["Class Pass Rate", f"{passed_count} / {total_students} ({pass_rate_pct:.1f}%)"])
    ws.append(["Total Marks Criteria", bulk_total_marks])
    ws.append(["Pass Marks Criteria", bulk_pass_marks])

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    
    filename = f"class_results_{bulk_id}.xlsx"
    return send_file(
        out,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename
    )

@app.route('/export-csv/<int:eval_id>')
def export_csv(eval_id):
    try:
        eval_data = get_evaluation_by_id(eval_id)
        if not eval_data:
            return "Evaluation not found.", 404
            
        dest = io.StringIO()
        writer = csv.writer(dest)
        
        total_marks = eval_data.get("total_marks", 0.0)
        pass_marks = eval_data.get("pass_marks", 0.0)
        awarded = eval_data.get("total_awarded_marks", 0.0)
        status = "PASS" if awarded >= pass_marks else "FAIL"

        # Metadata
        writer.writerow(["EvalIQ Evaluation Report"])
        writer.writerow([])
        writer.writerow(["Student Name", eval_data.get("student_name")])
        writer.writerow(["Student ID", eval_data.get("student_id")])
        writer.writerow(["Subject", eval_data.get("subject")])
        writer.writerow(["Timestamp", eval_data.get("timestamp")])
        writer.writerow(["Total Max Marks", eval_data.get("total_max_marks")])
        writer.writerow(["Total Awarded Marks", eval_data.get("total_awarded_marks")])
        writer.writerow(["Total Marks Criteria", total_marks])
        writer.writerow(["Pass Marks Criteria", pass_marks])
        writer.writerow(["Status", status])
        writer.writerow([])
        
        # Details headers
        writer.writerow([
            "Question No", "Question Text", "Max Marks", 
            "LLM Awarded Marks", "Similarity Score (%)", "Final Awarded Marks", 
            "Needs Manual Review", "Confidence", "Matched Points (LLM)", 
            "Semantic Matched Points", "Missing Points", "Feedback"
        ])
        
        for q in eval_data.get("questions_data", []):
            matched_llm = "; ".join(q.get("matched_points", []))
            matched_sem = "; ".join(q.get("semantic_matched_points", []))
            missing = "; ".join(q.get("missing_points", []))
            writer.writerow([
                q.get("question_no"),
                q.get("question_text"),
                q.get("max_marks"),
                q.get("awarded_marks"),
                f"{q.get('similarity_score', 0.0):.1f}%",
                q.get("final_awarded_marks", q.get("awarded_marks", 0.0)),
                "Yes" if q.get("needs_manual_review") else "No",
                q.get("confidence"),
                matched_llm,
                matched_sem,
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
        
        writer.writerow(["Evaluation ID", "Student Name", "Student ID", "Subject", "Total Max Marks", "Total Awarded Marks", "Total Marks Criteria", "Pass Marks Criteria", "Status", "Timestamp"])
        for row in evals:
            total_marks = row.get("total_marks", 0.0)
            pass_marks = row.get("pass_marks", 0.0)
            awarded = row.get("total_awarded_marks", 0.0)
            status = "PASS" if awarded >= pass_marks else "FAIL"
            writer.writerow([
                row.get("id"),
                row.get("student_name"),
                row.get("student_id"),
                row.get("subject"),
                row.get("total_max_marks"),
                row.get("total_awarded_marks"),
                total_marks,
                pass_marks,
                status,
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
