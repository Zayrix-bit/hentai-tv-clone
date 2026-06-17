FROM python:3.12-slim

WORKDIR /app

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the backend Python files (avoids copying frontend/node_modules)
COPY app.py hentai_scraper.py ./
# Hugging Face Spaces expose port 7860 by default for Docker spaces
EXPOSE 7860

# Run the Flask app with Gunicorn
# Using gthread worker class and threads to handle async routes efficiently
CMD ["gunicorn", "-b", "0.0.0.0:7860", "--workers", "2", "--threads", "4", "app:app"]
