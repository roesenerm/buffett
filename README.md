# Buffett App

A Flask application that analyzes 10-K filings using AI (Gemini) in the style of Warren Buffett.

## Features

- Fetch latest 10-K filings from SEC for a given stock ticker
- Extract key sections (Business, Risk Factors, MD&A, etc.)
- Summarize sections using Google Gemini AI as Warren Buffett
- Generate text-to-speech audio of the summaries

## API Endpoint

`GET /analyze/10k/<ticker>/<section>`

Returns JSON with summary and base64-encoded audio data.

Example: `/analyze/10k/AAPL/business`

Response:
```json
{
  "ticker": "AAPL",
  "section": "business",
  "summary": "...",
  "audio_data": "base64string",
  "audio_mime": "audio/wav"
}
```

## Setup

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Set environment variable: `GOOGLE_API_KEY=your_api_key`
4. Run: `flask run` (dev) or use Docker

## Deployment

### Using Docker

1. Build: `docker build -t buffett-app .`
2. Run: `docker run -p 5000:5000 -e GOOGLE_API_KEY=your_key buffett-app`

### Production

Use gunicorn: `gunicorn --bind 0.0.0.0:5000 buffett_app:app`

## Environment Variables

- `GOOGLE_API_KEY`: Required for Gemini API

## Notes

- Audio files are saved locally; consider cloud storage for production.
- Ensure compliance with SEC data usage policies.