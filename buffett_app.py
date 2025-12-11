import os
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, send_file, request, render_template
from google import genai
from google.genai import types
import re
import uuid
import base64
import io
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Load your Gemini API key from environment
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GEMINI_API_KEY:
    logger.error("GOOGLE_API_KEY not found in environment variables")
    raise ValueError("GOOGLE_API_KEY environment variable is required")

client = genai.Client(api_key=GEMINI_API_KEY)

headers = {"User-Agent": "Matthew matthew@example.com"}

def get_cik(ticker):
    """Resolve ticker to CIK using SEC API."""
    try:
        logger.info(f"Looking up CIK for ticker: {ticker}")
        url = f"https://www.sec.gov/files/company_tickers.json"
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        for entry in data.values():
            if entry["ticker"].lower() == ticker.lower():
                cik = str(entry["cik_str"]).zfill(10)
                logger.info(f"Found CIK {cik} for ticker {ticker}")
                return cik

        logger.warning(f"No CIK found for ticker: {ticker}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch CIK data for ticker {ticker}: {e}")
        return None
    except KeyError as e:
        logger.error(f"Unexpected data structure in CIK response for ticker {ticker}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in get_cik for ticker {ticker}: {e}")
        return None

def get_latest_10k_url(cik):
    """Fetch latest 10-K filing URL for a company."""
    try:
        logger.info(f"Fetching latest 10-K URL for CIK: {cik}")
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        forms = data["filings"]["recent"]["form"]
        for i, form in enumerate(forms):
            if form == "10-K":
                accession = data["filings"]["recent"]["accessionNumber"][i]
                primary_doc = data["filings"]["recent"]["primaryDocument"][i]
                archive_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{primary_doc}"
                logger.info(f"Found 10-K URL: {archive_url}")
                return archive_url

        logger.warning(f"No 10-K found for CIK: {cik}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch 10-K data for CIK {cik}: {e}")
        return None
    except KeyError as e:
        logger.error(f"Unexpected data structure in 10-K response for CIK {cik}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in get_latest_10k_url for CIK {cik}: {e}")
        return None

def fetch_10k_text(url):
    """Fetch raw text from EDGAR 10-K filing URL."""
    try:
        logger.info(f"Fetching 10-K text from URL: {url}")
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text(separator="\n")
        logger.info(f"Successfully fetched {len(text)} characters of 10-K text")
        return text
    except requests.exceptions.Timeout as e:
        logger.error(f"Timeout fetching 10-K from {url}: {e}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch 10-K from {url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in fetch_10k_text for URL {url}: {e}")
        return None

def extract_sections(text):
    """
    Extract major narrative sections from a 10-K filing using regex.
    Returns a dictionary with section names and full text.
    """
    try:
        logger.info("Extracting sections from 10-K text")
        sections = {}

        patterns = [
            (r"item\s+1\.*\s*business", "Business", r"item\s+1a"),
            (r"item\s+1a\.*\s*risk\s*factors", "Risk Factors", r"item\s+1b"),
            (r"item\s+7\.*\s*management", "Management's Discussion and Analysis", r"item\s+7a"),
            (r"item\s+7a", "Quantitative and Qualitative Disclosures", r"item\s+8"),
            (r"item\s+8", "Financial Statements", r"item\s+9"),
        ]

        for start_pattern, name, end_pattern in patterns:
            try:
                # Find all matches of the start pattern
                matches = list(re.finditer(start_pattern, text, re.IGNORECASE))
                if not matches:
                    logger.debug(f"No matches found for section: {name}")
                    continue

                # Use the *last* match (skips TOC, grabs real section body)
                start = matches[-1].start()

                end_match = re.search(end_pattern, text[start:], re.IGNORECASE)
                end = start + end_match.start() if end_match else len(text)

                section_text = text[start:end].strip()
                sections[name] = section_text
                logger.info(f"Extracted section '{name}' with {len(section_text)} characters")
            except Exception as e:
                logger.error(f"Error extracting section '{name}': {e}")
                continue

        logger.info(f"Successfully extracted {len(sections)} sections")
        return sections
    except Exception as e:
        logger.error(f"Unexpected error in extract_sections: {e}")
        return {}

def analyze_with_gemini(section_name, section_text):
    """Send section text to Gemini for summarization."""
    try:
        logger.info(f"Analyzing section '{section_name}' with Gemini AI")
        prompt = f"""
        You are Warren Buffett.
        Summarize financial documents clearly and concisely.
        Using tenets from the document 'The Warren Buffett Way' by Robert Hagstrom in your analysis.

        Section: {section_name}
        Text:
        {section_text}

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
        logger.info(f"Successfully generated summary for section '{section_name}'")
        return response.text
    except Exception as e:
        logger.error(f"Failed to analyze section '{section_name}' with Gemini: {e}")
        return f"Error: Unable to generate summary for {section_name}. {str(e)}"

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/analyze/10k/<ticker>/<section>")
def analyze_10k(ticker, section):
    try:
        logger.info(f"Starting analysis for ticker: {ticker}, section: {section}")

        # Step 1: Get CIK
        cik = get_cik(ticker)
        if not cik:
            logger.warning(f"CIK lookup failed for ticker: {ticker}")
            return jsonify({"error": "Ticker not found"}), 404

        # Step 2: Get latest 10-K URL
        url = get_latest_10k_url(cik)
        if not url:
            logger.warning(f"No 10-K found for CIK: {cik}")
            return jsonify({"error": "No 10-K found"}), 404

        # Step 3: Fetch 10-K text
        text = fetch_10k_text(url)
        if not text:
            logger.error(f"Failed to fetch 10-K text from URL: {url}")
            return jsonify({"error": "Failed to fetch 10-K content"}), 500

        # Step 4: Extract sections
        sections = extract_sections(text)
        if not sections:
            logger.warning("No sections extracted from 10-K")
            return jsonify({"error": "No sections found in 10-K"}), 404

        # Step 5: Find requested section
        normalized_sections = {k.lower(): v for k, v in sections.items()}
        section_key = section.lower()

        if section_key not in normalized_sections:
            logger.warning(f"Requested section '{section}' not found. Available: {list(sections.keys())}")
            return jsonify({"error": f"Section {section} not found"}), 404

        # Step 6: Analyze with Gemini
        summary = analyze_with_gemini(section, normalized_sections[section_key])
        if not summary or summary.startswith("Error:"):
            logger.error(f"Gemini analysis failed for section: {section}")
            return jsonify({"error": "Failed to generate summary"}), 500

        logger.info(f"Successfully completed analysis for {ticker} - {section}")

        # Generate TTS audio from summary using Gemini
        try:
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
        except Exception as e:
            logger.warning(f"TTS generation failed: {e}. Returning summary without audio.")
            # Return JSON with summary only if TTS fails
            return jsonify({"ticker": ticker, "section": section, "summary": summary})

    except Exception as e:
        logger.error(f"Unexpected error in analyze_10k for {ticker}/{section}: {e}")
        return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    app.run(debug=True)