import torch
from transformers import AutoTokenizer, AutoModel

# Load the pretrained model and tokenizer once at module level (cached on first run)
MODEL_NAME = 'sentence-transformers/all-MiniLM-L6-v2'
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model = AutoModel.from_pretrained(MODEL_NAME)

# Configurable threshold constant for matching a rubric point
SIMILARITY_THRESHOLD = 0.45

def mean_pooling(model_output, attention_mask):
    """
    Mean Pooling - Take attention mask into account for correct averaging.
    """
    token_embeddings = model_output[0] # First element of model_output contains all token embeddings
    input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
    return torch.sum(token_embeddings * input_mask_expanded, 1) / torch.clamp(input_mask_expanded.sum(1), min=1e-9)

def encode_texts(texts: list) -> torch.Tensor:
    """
    Encodes a list of text strings into normalized embedding vectors.
    """
    encoded_input = tokenizer(texts, padding=True, truncation=True, return_tensors='pt')
    with torch.no_grad():
        model_output = model(**encoded_input)
    sentence_embeddings = mean_pooling(model_output, encoded_input['attention_mask'])
    sentence_embeddings = torch.nn.functional.normalize(sentence_embeddings, p=2, dim=1)
    return sentence_embeddings

def get_similarity_score(student_answer: str, rubric_points: list) -> dict:
    """
    Computes semantic similarity between the student's answer and expected rubric points.
    
    Args:
        student_answer (str): The text answer provided by the student.
        rubric_points (list): A list of strings representing the grading criteria/expected key points.
        
    Returns:
        dict: {
            "similarity_score": <average similarity as percentage 0-100>,
            "matched_rubric_points": [<list of matched rubric point strings>]
        }
    """
    # Handle edge cases: empty student_answer or empty rubric_points
    if not student_answer or not student_answer.strip() or not rubric_points:
        return {
            "similarity_score": 0.0,
            "matched_rubric_points": []
        }
    
    # Filter empty rubric points
    rubric_points_clean = [p.strip() for p in rubric_points if p and p.strip()]
    if not rubric_points_clean:
        return {
            "similarity_score": 0.0,
            "matched_rubric_points": []
        }
    
    # 1. Encode student answer
    student_emb = encode_texts([student_answer.strip()])
    
    # 2. Encode rubric points
    rubric_embs = encode_texts(rubric_points_clean)
    
    # 3. Compute cosine similarities
    # Since embeddings are L2 normalized, cosine similarity is the dot product.
    # Shape of student_emb: (1, d). Shape of rubric_embs: (n, d).
    cos_scores = torch.mm(student_emb, rubric_embs.transpose(0, 1))[0]
    
    # Convert PyTorch tensor results to a standard Python list of floats
    scores_list = cos_scores.tolist()
    if not isinstance(scores_list, list):
        scores_list = [scores_list]
        
    matched_rubric_points = []
    clamped_scores = []
    
    for score, point in zip(scores_list, rubric_points_clean):
        score_val = float(score)
        # Check against configurable threshold constant
        if score_val >= SIMILARITY_THRESHOLD:
            matched_rubric_points.append(point)
        # Cosine similarity can be negative, clamp to 0.0
        clamped_scores.append(max(0.0, score_val))
        
    # Calculate average similarity score as percentage (0 to 100)
    avg_score = sum(clamped_scores) / len(clamped_scores)
    similarity_score_pct = round(avg_score * 100.0, 1)
    
    return {
        "similarity_score": similarity_score_pct,
        "matched_rubric_points": matched_rubric_points
    }
