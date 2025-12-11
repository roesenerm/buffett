import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, send_file, request, render_template
from google import genai
from google.genai import types
import re
import uuid
import base64
import io

app = Flask(__name__)

# Load your Gemini API key from environment
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

headers = {"User-Agent": "Matthew matthew@example.com"}

def get_cik(ticker):
    """Resolve ticker to CIK using SEC API."""
    url = f"https://www.sec.gov/files/company_tickers.json"
    data = requests.get(url, headers=headers).json()
    for entry in data.values():
        if entry["ticker"].lower() == ticker.lower():
            return str(entry["cik_str"]).zfill(10)
    return None

def get_latest_10k_url(cik):
    """Fetch latest 10-K filing URL for a company."""
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    data = requests.get(url, headers=headers).json()
    forms = data["filings"]["recent"]["form"]
    for i, form in enumerate(forms):
        if form == "10-K":
            accession = data["filings"]["recent"]["accessionNumber"][i]
            primary_doc = data["filings"]["recent"]["primaryDocument"][i]
            archive_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{primary_doc}"
            return archive_url
    return None

def fetch_10k_text(url):
    """Fetch raw text from EDGAR 10-K filing URL."""
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    return soup.get_text(separator="\n")

def extract_sections(text):
    """
    Extract major narrative sections from a 10-K filing using regex.
    Returns a dictionary with section names and full text.
    """
    sections = {}
    
    patterns = [
        (r"item\s+1\.*\s*business", "Business", r"item\s+1a"),
        (r"item\s+1a\.*\s*risk\s*factors", "Risk Factors", r"item\s+1b"),
        (r"item\s+7\.*\s*management", "Management’s Discussion and Analysis", r"item\s+7a"),
        (r"item\s+7a", "Quantitative and Qualitative Disclosures", r"item\s+8"),
        (r"item\s+8", "Financial Statements", r"item\s+9"),
    ]
    
    for start_pattern, name, end_pattern in patterns:
        # Find all matches of the start pattern
        matches = list(re.finditer(start_pattern, text, re.IGNORECASE))
        if not matches:
            continue
        
        # Use the *last* match (skips TOC, grabs real section body)
        start = matches[-1].start()
        
        end_match = re.search(end_pattern, text[start:], re.IGNORECASE)
        end = start + end_match.start() if end_match else len(text)
        
        section_text = text[start:end].strip()
        sections[name] = section_text
    
    return sections

def analyze_with_gemini(section_name, section_text):
    """Send section text to Gemini for summarization."""
    prompt = f"""
    You are analyzing a 10-K filing.
    Section: {section_name}
    Text:
    {section_text}  # chunk to avoid token limits

    Task: Summarize the key points in plain English.
    """
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        config=types.GenerateContentConfig(
            system_instruction="You are Warren Buffett. " \
            "Summarize financial documents clearly and concisely. " \
            "Using tenets from the document 'The Warren Buffett Way' by Robert Hagstrom in your analysis."),
        contents=prompt
    )
    return response.text

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/analyze/10k/<ticker>/<section>")
def analyze_10k(ticker, section):
    cik = get_cik(ticker)
    if not cik:
        return jsonify({"error": "Ticker not found"}), 404
    url = get_latest_10k_url(cik)
    if not url:
        return jsonify({"error": "No 10-K found"}), 404
    text = fetch_10k_text(url)
    sections = extract_sections(text)

    # Normalize keys for lookup
    normalized_sections = {k.lower(): v for k, v in sections.items()}
    #print (normalized_sections)
    section_key = section.lower()

    if section_key not in normalized_sections:
        return jsonify({"error": f"Section {section} not found"}), 404

    summary = analyze_with_gemini(section, normalized_sections[section_key])

    # Generate TTS audio from summary using Gemini
    tts_response = client.models.generate_content(
        model="gemini-2.5-flash-preview-tts",
        contents=f"Read this summary: {summary}",
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name='Kore',
                    )
                )
            ),
        )
    )

    data = tts_response.candidates[0].content.parts[0].inline_data.data

    # Encode audio data to base64 for JSON response
    audio_base64 = base64.b64encode(data).decode('utf-8')

    # Return JSON with summary and audio data
    return jsonify({"ticker": ticker, "section": section, "summary": summary, "audio_data": audio_base64, "audio_mime": "audio/wav"})

if __name__ == "__main__":
    app.run(debug=True)