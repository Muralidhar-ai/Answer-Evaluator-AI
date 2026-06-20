import base64
import os
import fitz  # PyMuPDF
import re
import json
from groq import Groq
from config import Config

def get_groq_client():
    if not Config.GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY is not set. Please add it to your environment or .env file.")
    return Groq(api_key=Config.GROQ_API_KEY)

def convert_pdf_to_images(pdf_bytes):
    """
    Converts PDF pages to base64-encoded PNG image strings in memory.
    """
    images_base64 = []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            # 150 DPI is standard, keeping quality readable but memory load small
            pix = page.get_pixmap(dpi=150)
            img_data = pix.tobytes("png")
            encoded = base64.b64encode(img_data).decode("utf-8")
            images_base64.append(f"data:image/png;base64,{encoded}")
    except Exception as e:
        raise ValueError(f"Failed to process PDF file: {str(e)}")
    return images_base64

def encode_image(image_bytes, filename):
    """
    Encodes an image (PNG/JPG) to a base64 data URL.
    """
    ext = os.path.splitext(filename)[1].lower().replace(".", "")
    if ext not in ["png", "jpg", "jpeg", "webp"]:
        ext = "png"  # fallback
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:image/{ext};base64,{encoded}"

def parse_json_from_response(text):
    """
    Robustly extracts and parses JSON from the model's text response.
    """
    text = text.strip()
    # Try finding markdown code block
    match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if match:
        text = match.group(1)
    else:
        match = re.search(r'```\s*(.*?)\s*```', text, re.DOTALL)
        if match:
            text = match.group(1)
            
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fallback: find the first [ or { and last ] or }, ignoring -1 (not found)
        candidates_start = [pos for pos in [text.find('['), text.find('{')] if pos != -1]
        candidates_end = [pos for pos in [text.rfind(']'), text.rfind('}')] if pos != -1]
        if candidates_start and candidates_end:
            start_idx = min(candidates_start)
            end_idx = max(candidates_end)
            if start_idx < end_idx:
                try:
                    return json.loads(text[start_idx:end_idx+1])
                except json.JSONDecodeError:
                    pass
        raise ValueError(f"Could not parse valid JSON from the model response. Raw response: {text}")

def normalize_extracted_questions(parsed_json):
    """
    Ensures that the output of extract_questions_or_rubric is always a list of dictionaries.
    """
    items = []
    if isinstance(parsed_json, list):
        items = parsed_json
    elif isinstance(parsed_json, dict):
        # Look for a list inside the values (e.g. {"questions": [...]})
        list_found = False
        for val in parsed_json.values():
            if isinstance(val, list):
                items = val
                list_found = True
                break
        if not list_found:
            items = [parsed_json]
    else:
        # Fallback for unexpected type
        items = [parsed_json]

    normalized = []
    for item in items:
        if isinstance(item, dict):
            # Ensure required keys exist
            normalized.append({
                "question_no": str(item.get("question_no", "")),
                "question_text": str(item.get("question_text", "") or item.get("question", "")),
                "max_marks": item.get("max_marks"),
                "rubric_points": item.get("rubric_points") if isinstance(item.get("rubric_points"), list) else ([item.get("rubric_points")] if item.get("rubric_points") else [])
            })
        elif isinstance(item, str):
            # If the item is a string, wrap it gracefully
            normalized.append({
                "question_no": "",
                "question_text": item,
                "max_marks": None,
                "rubric_points": []
            })
    return normalized

def extract_questions_or_rubric(file_bytes=None, filename=None, paste_text=None, is_rubric=False):
    """
    Extracts structure of questions (or rubrics) using Groq.
    Returns: list of dicts: [{question_no, question_text, max_marks, rubric_points: []}]
    """
    client = get_groq_client()
    model = Config.GROQ_MODEL
    
    prompt = (
        "Extract all questions from this document with their question numbers, marks allotted "
        "(if mentioned), and full question text. "
    )
    if is_rubric:
        prompt += "Since this is an answer key, also extract the expected key points/model answer for each question. "
    else:
        prompt += "If this is an answer key, also extract the expected key points/model answer for each question. "
        
    prompt += "Return strict JSON: [{\"question_no\": \"string\", \"question_text\": \"string\", \"max_marks\": number_or_null, \"rubric_points\": [\"string\"]}]"

    # CASE 1: Paste Text
    if paste_text:
        messages = [
            {
                "role": "user",
                "content": f"{prompt}\n\nDocument text:\n{paste_text}"
            }
        ]
    # CASE 2: Uploaded PDF or Image
    else:
        if not file_bytes:
            raise ValueError("No file contents provided for extraction.")
            
        content = [{"type": "text", "text": prompt}]
        
        if filename.lower().endswith('.pdf'):
            # Multi-page PDF to base64 images
            images = convert_pdf_to_images(file_bytes)
            for img in images:
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": img
                    }
                })
        else:
            # Single Image
            img_data_url = encode_image(file_bytes, filename)
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": img_data_url
                }
            })
            
        messages = [
            {
                "role": "user",
                "content": content
            }
        ]

    # Determine if this request includes image content (vision/multimodal)
    # JSON mode (response_format=json_object) is NOT supported for vision requests
    has_images = isinstance(messages[0].get("content"), list) and any(
        item.get("type") == "image_url" for item in messages[0].get("content", [])
    ) if messages else False

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            # Only use JSON mode for text-only (non-vision) requests
            response_format={"type": "json_object"} if not has_images else None
        )
        response_text = response.choices[0].message.content
        parsed = parse_json_from_response(response_text)
        return normalize_extracted_questions(parsed)
    except Exception as e:
        raise ValueError(f"Groq Extraction API failed: {str(e)}")

def ocr_student_sheet(file_bytes, filename):
    """
    Extracts handwritten text from student answer sheet using Groq Vision.
    Returns: string (transcribed raw text with preserved question numbers and structure).
    """
    client = get_groq_client()
    model = Config.GROQ_MODEL
    
    prompt = (
        "Extract all handwritten text from this answer sheet image exactly as written, "
        "preserving question numbers and structure. Do not correct spelling/grammar. "
        "Flag any unclear or illegible sections instead of guessing."
    )
    
    content = [{"type": "text", "text": prompt}]
    
    if filename.lower().endswith('.pdf'):
        images = convert_pdf_to_images(file_bytes)
        for img in images:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": img
                }
            })
    else:
        img_data_url = encode_image(file_bytes, filename)
        content.append({
            "type": "image_url",
            "image_url": {
                "url": img_data_url
            }
        })
        
    messages = [
        {
            "role": "user",
            "content": content
        }
    ]
    
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1
        )
        return response.choices[0].message.content
    except Exception as e:
        raise ValueError(f"Groq Student Sheet OCR API failed: {str(e)}")
