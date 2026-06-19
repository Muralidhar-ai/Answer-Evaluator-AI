# AI Answer Sheet Evaluator

A multi-modal AI system built with Flask that automatically evaluates handwritten student answer sheets against an uploaded question paper and rubric using the Groq API (powered by `llama-4-maverick` / vision + text capable models).

## Features

- **Three Independent Uploads**:
  1. Question Paper (PDF, Image, or plain text paste)
  2. Answer Key / Rubric (PDF, Image, or plain text paste)
  3. Student Answer Sheet (PDF or Image, handwritten)
- **Automatic Document Alignment**: Autodetects question numbers and falls back to semantic context matching if student sheet numbering is misaligned.
- **Editable Verification Step**: Instructors can preview aligned text, review OCR, and manually key in marks before starting the evaluation.
- **Dual-Language Feedback Toggle**: Instantly toggles student feedback between English and Tamil.
- **SQLite Evaluation Logs**: Saves completed evaluation history and supports real-time score overrides and overrides logging.
- **Render Ready**: Optimized dependency configuration using standard wheel installations.

---

## Tech Stack

- **Backend**: Flask (Python)
- **AI Integration**: Groq API
- **File Handling**: PyMuPDF (Fitz) for memory-efficient PDF-to-image extraction (avoids binary wrappers like Poppler on Windows/Render)
- **Database**: SQLite3 (built-in)
- **Frontend**: Bootstrap 5, FontAwesome, Vanilla JS & CSS

---

## Local Setup Instructions

### Prerequisites
Make sure Python 3.8+ is installed on your system.

### 1. Clone or Navigate to the Directory
```bash
cd "Ans Eval"
```

### 2. Set Up Virtual Environment & Install Dependencies
```bash
python -m venv venv
venv\Scripts\activate       # On Windows
source venv/bin/activate    # On macOS/Linux

pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your Groq API credentials:
```bash
cp .env.example .env
```
Open `.env` and configure:
- `GROQ_API_KEY`: Your Groq API key.
- `GROQ_MODEL`: Set to `llama-4-maverick` or your choice of Vision models like `llama-3.2-11b-vision-preview`.

### 4. Run the Application
```bash
python app.py
```
Open your browser and navigate to `http://127.0.0.1:5000/`.

---

## Render Deployment Instructions

This repository is optimized to deploy directly onto [Render](https://render.com).

### Step-by-Step Deployment
1. **Push Code to Git**: Put your workspace files into a GitHub/GitLab repository.
2. **Create Web Service**:
   - Go to Render Dashboard -> **New** -> **Web Service**.
   - Connect your GitHub repository.
3. **Build & Start Commands**:
   - **Environment**: `Python`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app` (already included in `requirements.txt`)
4. **Environment Variables**:
   Add the following environment variables in Render:
   - `GROQ_API_KEY`: *(Your secret Groq key)*
   - `GROQ_MODEL`: `llama-4-maverick` (or target vision model name)
   - `FLASK_SECRET_KEY`: *(Generate a secure random string)*
   - `PORT`: `10000` (Render binds to this automatically, or leaves default)
5. Click **Deploy Web Service**. Render will build the environment, start Gunicorn, and expose the public link!
