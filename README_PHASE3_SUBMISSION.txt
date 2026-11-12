Phase 3 deployment checklist

1. Push this project to the individual repository: amjose15/student-academic-history-api
2. In Render, create a NEW Web Service connected to that individual repository.
3. Build command: pip install -r requirements.txt
4. Start command: uvicorn main:app --host 0.0.0.0 --port $PORT
5. Wait for GitHub Actions workflow 'FastAPI CI Quality Gate' to finish green.
6. Capture the actual green GitHub Actions run page as ci_proof.png.
7. Copy the actual workflow run logs into ci_logs.txt.
8. Put the new Render base URL (no trailing slash) into api_url.txt.
9. Submit api_url.txt, ci_proof.png, and ci_logs.txt individually in Moodle.

Do not submit the old Phase 2 URL unless you verify that it is now deployed from this individual repository.
