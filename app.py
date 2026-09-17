import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"


def call_groq(report_text):
    system_prompt = (
        "You are a disaster-report parser. Given a citizen's raw text report, "
        "extract ONLY a JSON object with these fields: "
        "location (string), category (one of rescue, road_block, medical, shelter, other), "
        "severity (integer 1-5), people_count (integer), summary (short string). "
        "Respond with ONLY the JSON object, no extra text."
    )

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": report_text},
        ],
        "temperature": 0.2,
        "max_tokens": 300,
    }

    resp = requests.post(
        GROQ_ENDPOINT,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + GROQ_API_KEY,
        },
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    raw_content = data["choices"][0]["message"]["content"].strip()

    if raw_content.startswith("```"):
        raw_content = raw_content.strip("`")
        raw_content = raw_content.replace("json", "", 1).strip()

    return json.loads(raw_content)


def save_to_supabase(structured, raw_text):
    row = {
        "raw_text": raw_text,
        "location": structured.get ("location", "unknown"),
        "category": structured.get("category", "other"),
        "severity": structured.get("severity", 1),
        "people_count": structured.get("people_count", 0),
        "summary": structured.get("summary", ""),
        "status": "open",
    }

    resp = requests.post(
        SUPABASE_URL + "/rest/v1/reports",
        headers={
            "Content-Type": "application/json",
            "apikey": SUPABASE_KEY,
            "Authorization": "Bearer " + SUPABASE_KEY,
            "Prefer": "return=representation",
        },
        json=row,
        timeout=10,
    )
    resp.raise_for_status()
    result = resp.json()
    return result[0] if isinstance(result, list) and result else result


@app.route("/reports", methods=["POST"])
def create_report():
    body = request.get_json(silent=True) or {}
    report_text = (body.get("report_text") or "").strip()

    if not report_text:
        return jsonify({"error": "report_text is required"}), 400

    if not GROQ_API_KEY or not SUPABASE_URL or not SUPABASE_KEY:
        return jsonify({"error": "Server not configured"}), 500

    try:
        structured = call_groq(report_text)
    except Exception as e:
        return jsonify({"error": "Failed to parse report", "details": str(e)}), 502

    try:
        saved_row = save_to_supabase(structured, report_text)
    except Exception as e:
        return jsonify({"error": "Failed to save report", "details": str(e)}), 502

    return jsonify(saved_row), 200


@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "RescueGraph AI backend is running"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
