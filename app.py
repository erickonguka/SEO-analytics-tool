import os
import json
from flask import Flask, request, jsonify, render_template
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
import re
import google.generativeai as genai
from datetime import datetime, timedelta

app = Flask(__name__)

# Configure the AI API key
genai.configure(api_key=os.environ.get("API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

# Store request counts per IP
request_counts = {}

# Function to validate URLs
def validate_url(url):
    if not url.startswith(('http://', 'https://')):
        url = 'http://' + url
    return url

# Function to generate SEO keywords using generative AI based on website content
def generate_keywords(website_text):
    prompt = f"Analyze the following website content and generate 50 effective SEO keywords:\n{website_text}"
    response = model.generate_content(prompt)
    try:
        keywords = response.candidates[0].content.parts[0].text.strip()
    except (IndexError, AttributeError) as e:
        keywords = f"Error generating AI keywords: {str(e)}"

    return keywords

def scrape_website(url):
    data = {
        "titles": [],
        "descriptions": [],
        "phone_numbers": [],
        "emails": [],
        "locations": [],
        "all_headers": [], 
        "paragraphs": [], 
        "links": [],
        "keywords": []
    }

    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise an error for bad responses
        soup = BeautifulSoup(response.text, 'html.parser')

        # Extracting title
        title = soup.find('title')
        if title:
            data['titles'].append(title.text.strip())

        # Extracting meta description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and 'content' in meta_desc.attrs:
            data['descriptions'].append(meta_desc['content'].strip())

        # Extracting all headers (h1, h2, h3)
        headers = []
        for i in range(1, 4):  # Loop through h1, h2, h3 tags
            headers += soup.find_all(f'h{i}')
        data['all_headers'] = [header.text.strip() for header in headers]

        # Extracting the first 5 paragraphs
        paragraphs = soup.find_all('p')
        data['paragraphs'] = [para.text.strip() for para in paragraphs[:5]]

        # Extracting the first 10 links
        links = soup.find_all('a', href=True)
        data['links'] = [{"href": link['href'], "text": link.text.strip()} for link in links[:10]]

        # Extracting phone numbers using regex
        phone_pattern = re.compile(r'\+?\d[\d -]{8,}\d')
        data['phone_numbers'] = phone_pattern.findall(soup.get_text())

        # Extracting emails using regex
        email_pattern = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
        data['emails'] = email_pattern.findall(soup.get_text())

        # Extracting possible locations based on keywords
        location_keywords = ['location', 'address', 'city', 'country']
        for keyword in location_keywords:
            loc = soup.find(text=re.compile(keyword, re.IGNORECASE))
            if loc:
                data['locations'].append(loc.strip())

        # Keyword generation
        combined_text = ' '.join(data['titles'] + data['all_headers'] + data['paragraphs'])
        data['keywords'] = generate_keywords(combined_text)

    except requests.RequestException as e:
        return {"error": str(e)}

    return data

# Function to generate AI summary
def generate_ai_summary(scraped_data):
    message = (
        f"Analyze the following data from a website and generate only 600 words actionable SEO insights and summary: "
        f"Titles: {scraped_data['titles']}, Descriptions: {scraped_data['descriptions']}, "
        f"All Headers: {scraped_data['all_headers']}, "
        f"Phone Numbers: {scraped_data['phone_numbers']}, Emails: {scraped_data['emails']}, "
        f"Locations: {scraped_data['locations']}, Paragraphs: {scraped_data['paragraphs']}, "
        f"Links: {scraped_data['links']}."
    )
    
    response = model.generate_content(message)

    try:
        ai_summary_text = response.candidates[0].content.parts[0].text.strip()
    except (IndexError, AttributeError) as e:
        ai_summary_text = f"Error extracting AI summary: {str(e)}"

    return ai_summary_text

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    user_ip = request.remote_addr
    input_data = request.json.get('link')

    if not input_data:
        return jsonify({"error": "URL is required"}), 400

    # Initialize request count for the user if not already present
    current_time = datetime.now()
    if user_ip not in request_counts:
        request_counts[user_ip] = {
            "count": 0,
            "timestamp": current_time
        }

    # Check if the user has exceeded the daily limit
    if (current_time - request_counts[user_ip]["timestamp"]) > timedelta(hours=2):
        request_counts[user_ip]["count"] = 0
        request_counts[user_ip]["timestamp"] = current_time

    if request_counts[user_ip]["count"] >= 5:
        return jsonify({"error": "Daily limit of 5 requests exceeded"}), 429

    # Proceed with the analysis
    url = validate_url(input_data)
    scraped_data = scrape_website(url)

    if "error" in scraped_data:
        return jsonify({"error": scraped_data["error"]}), 500

    ai_summary = generate_ai_summary(scraped_data)

    # Calculate SEO score directly within this function
    score = 2
    if scraped_data['titles']:  
        score += 25

    if scraped_data['descriptions']: 
        score += 25

    if scraped_data['all_headers']: 
        score += 15

    if scraped_data['links']: 
        score += 10

    if scraped_data['paragraphs']: 
        score += 15

    # Set the calculated score
    scraped_data['score'] = score

    result = {
        "ai_summary": ai_summary,
        "keywords": scraped_data['keywords'],
        "score": score
    }

    try:
        with open("user_requests.json", "r") as f:
            existing_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        existing_data = []

    existing_data.append({"ip": user_ip, "url": url})

    with open("user_requests.json", "w") as f:
        json.dump(existing_data, f)

    # Increment the request count
    request_counts[user_ip]["count"] += 1

    return jsonify(result)

if __name__ == '__main__':
    app.run(debug=True)
