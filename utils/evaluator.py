import json
from groq import Groq
from config import Config
from utils.ocr import parse_json_from_response

def get_groq_client():
    if not Config.GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY is not set. Please add it to your environment or .env file.")
    return Groq(api_key=Config.GROQ_API_KEY)

def normalize_aligned_data(aligned_data):
    """
    Ensures that aligned data is always parsed into a list of dictionaries.
    """
    items = []
    if isinstance(aligned_data, list):
        items = aligned_data
    elif isinstance(aligned_data, dict):
        list_found = False
        for val in aligned_data.values():
            if isinstance(val, list):
                items = val
                list_found = True
                break
        if not list_found:
            items = [aligned_data]
    else:
        items = []

    normalized = []
    for item in items:
        if isinstance(item, dict):
            normalized.append({
                "question_no": str(item.get("question_no", "")),
                "student_answer": str(item.get("student_answer", "Not Attempted")),
                "max_marks": item.get("max_marks"),
                "rubric_points": item.get("rubric_points")
            })
        elif isinstance(item, str):
            normalized.append({
                "question_no": "",
                "student_answer": item,
                "max_marks": None,
                "rubric_points": []
            })
    return normalized

def align_answers(questions, rubric, student_ocr):
    """
    Aligns questions, rubrics, and student OCR transcript by matching question numbers or
    using semantic similarity when numbering doesn't align.
    Returns: list of aligned questions: [{question_no, question_text, max_marks, rubric_points, student_answer}]
    """
    client = get_groq_client()
    model = Config.GROQ_MODEL

    alignment_prompt = (
        "You are an academic exam administrator. You are given:\n"
        f"1. Extracted Question Paper: {json.dumps(questions)}\n"
        f"2. Rubric / Expected Answers: {json.dumps(rubric)}\n"
        f"3. Student's Raw OCR Answer Sheet text:\n{student_ocr}\n\n"
        "Your task is to associate/align the student's answer text to each question from the Question Paper.\n"
        "- Match by question numbers if they match.\n"
        "- If the numbering does not match or is missing in the OCR text, perform semantic alignment (infer which answer matches which question text based on subject matter, key words, or rubric context).\n"
        "- Preserve the student's handwritten answer text exactly as transcribed in the OCR (do not summarize or edit spelling/grammar).\n"
        "- If a question was clearly not attempted, set the student_answer to 'Not Attempted'.\n"
        "- Make sure EVERY question in the Question Paper is present in the final list.\n"
        "- Integrate the rubric_points list from the Rubric into the matching question. If a question is in the question paper but not in the rubric, set rubric_points to empty list [].\n\n"
        "Return strict JSON array of objects: "
        "[{\"question_no\": \"string\", \"question_text\": \"string\", \"max_marks\": number_or_null, \"rubric_points\": [\"string\"], \"student_answer\": \"string\"}]"
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": alignment_prompt}],
            temperature=0.1,
        )
        response_text = response.choices[0].message.content
        raw_aligned = parse_json_from_response(response_text)
        aligned_data = normalize_aligned_data(raw_aligned)
        
        # Cross-check and merge properties from questions/rubric if the LLM output is missing any
        # This makes the alignment logic extremely robust.
        merged_data = []
        for q in questions:
            if not isinstance(q, dict):
                continue
            q_no = str(q.get("question_no", ""))
            
            # Try to find corresponding aligned item
            matched_aligned = None
            for item in aligned_data:
                if str(item.get("question_no", "")) == q_no:
                    matched_aligned = item
                    break
            
            if not matched_aligned:
                # Try partial match or fallback
                for item in aligned_data:
                    if q_no in str(item.get("question_no", "")):
                        matched_aligned = item
                        break
            
            # Find rubric points for this question if missing
            rubric_points = []
            for r in rubric:
                if isinstance(r, dict) and str(r.get("question_no", "")) == q_no:
                    rubric_points = r.get("rubric_points", [])
                    break
            
            # Assemble item
            student_ans = "Not Attempted"
            if matched_aligned:
                student_ans = matched_aligned.get("student_answer", "Not Attempted")
                
            merged_data.append({
                "question_no": q_no,
                "question_text": q.get("question_text", ""),
                "max_marks": q.get("max_marks") or (matched_aligned.get("max_marks") if matched_aligned else None),
                "rubric_points": rubric_points or (matched_aligned.get("rubric_points") if matched_aligned else []),
                "student_answer": student_ans
            })
            
        return merged_data
    except Exception as e:
        # Fallback in case LLM alignment fails entirely: create a mock/empty alignment
        fallback_data = []
        for q in questions:
            if not isinstance(q, dict):
                continue
            q_no = str(q.get("question_no", ""))
            rubric_points = []
            for r in rubric:
                if isinstance(r, dict) and str(r.get("question_no", "")) == q_no:
                    rubric_points = r.get("rubric_points", [])
                    break
            fallback_data.append({
                "question_no": q_no,
                "question_text": q.get("question_text", ""),
                "max_marks": q.get("max_marks"),
                "rubric_points": rubric_points,
                "student_answer": "Not Attempted (Alignment Failed)"
            })
        return fallback_data

def evaluate_student_answer(q):
    """
    Evaluates a single student answer against expected rubrics using Groq.
    q: dict with keys {question_no, question_text, max_marks, rubric_points, student_answer}
    """
    q_no = q.get("question_no", "")
    q_text = q.get("question_text", "")
    max_marks = q.get("max_marks")
    # Handle edge case where max_marks is None/not set
    if max_marks is None:
        max_marks = 0
    rubric_points = q.get("rubric_points", [])
    student_answer = q.get("student_answer", "").strip()

    # Fast check: If student did not attempt the question, award 0 and skip API call
    if not student_answer or student_answer.lower() in ["not attempted", "not attempted (alignment failed)"]:
        return {
            "question_no": q_no,
            "max_marks": max_marks,
            "awarded_marks": 0.0,
            "matched_points": [],
            "missing_points": rubric_points,
            "feedback": "Question not attempted.",
            "feedback_tamil": "இந்த கேள்விக்கு விடை எழுதப்படவில்லை.",
            "confidence": "High"
        }

    client = get_groq_client()
    model = Config.GROQ_MODEL

    eval_prompt = (
        "You are an expert academic answer sheet evaluator for Indian university exams.\n"
        "Evaluate the student's answer against the rubric based on concept match, not exact wording. "
        "Award partial marks fairly but strictly.\n\n"
        "Question details:\n"
        f"- Question No: {q_no}\n"
        f"- Question Text: {q_text}\n"
        f"- Maximum Marks: {max_marks}\n"
        f"- Expected Rubric / Key points: {json.dumps(rubric_points)}\n\n"
        "Student's Answer:\n"
        f"{student_answer}\n\n"
        "Respond only in JSON:\n"
        "{\n"
        f"  \"question_no\": \"{q_no}\",\n"
        f"  \"max_marks\": {max_marks},\n"
        "  \"awarded_marks\": number,\n"
        "  \"matched_points\": [\"string\"],\n"
        "  \"missing_points\": [\"string\"],\n"
        "  \"feedback\": \"string\",\n"
        "  \"feedback_tamil\": \"tamil feedback string\",\n"
        "  \"confidence\": \"string (High, Medium, or Low)\"\n"
        "}"
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": eval_prompt}],
            temperature=0.1,
        )
        response_text = response.choices[0].message.content
        result = parse_json_from_response(response_text)
        
        # Ensure correct key types
        try:
            result["awarded_marks"] = float(result.get("awarded_marks", 0))
            result["max_marks"] = float(result.get("max_marks", max_marks))
        except (ValueError, TypeError):
            result["awarded_marks"] = 0.0
            result["max_marks"] = float(max_marks)

        # Safety bound
        if result["awarded_marks"] > result["max_marks"]:
            result["awarded_marks"] = result["max_marks"]
        if result["awarded_marks"] < 0:
            result["awarded_marks"] = 0.0
            
        return result
    except Exception as e:
        # Return fallback error dict for this question
        return {
            "question_no": q_no,
            "max_marks": max_marks,
            "awarded_marks": 0.0,
            "matched_points": [],
            "missing_points": rubric_points,
            "feedback": f"Evaluation error: {str(e)}",
            "feedback_tamil": f"மதிப்பீட்டு பிழை: {str(e)}",
            "confidence": "Low"
        }

def evaluate_all(aligned_questions):
    """
    Evaluates list of aligned questions and aggregates results.
    """
    results = []
    total_max = 0.0
    total_awarded = 0.0

    for q in aligned_questions:
        eval_res = evaluate_student_answer(q)
        # Store original student answer and question text inside results for displaying
        eval_res["question_text"] = q.get("question_text", "")
        eval_res["student_answer"] = q.get("student_answer", "")
        eval_res["rubric_points"] = q.get("rubric_points", [])
        
        results.append(eval_res)
        total_max += float(eval_res.get("max_marks", 0))
        total_awarded += float(eval_res.get("awarded_marks", 0))

    return {
        "total_max_marks": total_max,
        "total_awarded_marks": total_awarded,
        "questions": results
    }
