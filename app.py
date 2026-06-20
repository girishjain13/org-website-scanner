import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
from io import BytesIO
from docx import Document
import re
from collections import defaultdict
import time

st.set_page_config(page_title="UX & IA Audit Tool", layout="wide")

# -----------------------------
# 1. URL NORMALIZER & FILTER
# -----------------------------
def normalize_url(url):
    parsed = urlparse(url)
    clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if clean != parsed.scheme + "://" + parsed.netloc + "/":
        clean = clean.rstrip('/')
    return clean

# -----------------------------
# 2. CONTENT TYPE CLASSIFIER
# -----------------------------
def classify_content_type(url, soup):
    url_lower = url.lower()
    if any(x in url_lower for x in ['/blog/', '/article/', '/news/', '/post/']):
        return 'Blog/Article'
    elif any(x in url_lower for x in ['/product/', '/shop/', '/item/', '/store/']):
        return 'Product Page'
    elif any(x in url_lower for x in ['/landing/', '/campaign/', '/promo/']):
        return 'Landing Page'
    elif any(x in url_lower for x in ['/about/', '/team/', '/company/']):
        return 'About Page'
    elif any(x in url_lower for x in ['/contact/', '/support/', '/help/']):
        return 'Contact/Support'
    elif any(x in url_lower for x in ['/category/', '/tag/', '/archive/']):
        return 'Category/Archive'
    elif soup.find('article'):
        return 'Blog/Article'
    elif soup.find('form') and len(soup.find_all('input')) > 5:
        return 'Form Page'
    else:
        return 'Standard Page'

# -----------------------------
# 3. UX/IA ANALYSIS WORKER
# -----------------------------
def fetch_and_analyze(url, domain, integration_patterns):
    links = set()
    integrations_found = set()
    forms_found = []
    has_calculator = False
    
    # UX/IA Data
    page_data = {
        'url': url,
        'title': '',
        'meta_description': '',
        'h1_count': 0,
        'h1_text': [],
        'h2_count': 0,
        'h3_count': 0,
        'word_count': 0,
        'content_type': '',
        'broken_links': [],
        'redirects': [],
        'cta_buttons': [],
        'anchor_texts': [],
        'images_without_alt': 0,
        'forms_without_labels': 0,
        'nav_links': [],
        'footer_links': []
    }
    
    # FILTER: Ignore non-HTML files
    if any(url.lower().endswith(ext) for ext in ['.pdf', '.jpg', '.jpeg', '.png', '.gif', '.zip', '.xml', '.css', '.js', '.doc', '.docx']):
        return url, set(), set(), [], False, page_data

    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        res = requests.get(url, timeout=10, headers=headers, allow_redirects=True)
        
        if 'text/html' not in res.headers.get('Content-Type', ''):
            return url, set(), set(), [], False, page_data

        # Track redirects
        if len(res.history) > 0:
            page_data['redirects'] = [r.url for r in res.history]

        soup = BeautifulSoup(res.text, "html.parser")
        all_text = str(soup)
        
        # --- UX/IA ANALYSIS ---
        
        # Page Title & Meta
        title_tag = soup.find('title')
        page_data['title'] = title_tag.text.strip() if title_tag else 'Missing'
        
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        page_data['meta_description'] = meta_desc.get('content', 'Missing') if meta_desc else 'Missing'
        
        # Heading Structure
        h1_tags = soup.find_all('h1')
        page_data['h1_count'] = len(h1_tags)
        page_data['h1_text'] = [h1.get_text(strip=True) for h1 in h1_tags[:3]]
        page_data['h2_count'] = len(soup.find_all('h2'))
        page_data['h3_count'] = len(soup.find_all('h3'))
        
        # Word Count
        body_text = soup.get_text(separator=' ', strip=True)
        page_data['word_count'] = len(body_text.split())
        
        # Content Type
        page_data['content_type'] = classify_content_type(url, soup)
        
        # Navigation Menus
        nav = soup.find('nav') or soup.find('header')
        if nav:
            nav_links = [a.get_text(strip=True) for a in nav.find_all('a', href=True)[:20]]
            page_data['nav_links'] = nav_links
        
        footer = soup.find('footer')
        if footer:
            footer_links = [a.get_text(strip=True) for a in footer.find_all('a', href=True)[:20]]
            page_data['footer_links'] = footer_links
        
        # CTA Buttons
        cta_keywords = ['sign up', 'get started', 'buy now', 'learn more', 'contact', 'download', 'subscribe', 'register']
        for button in soup.find_all(['button', 'a']):
            button_text = button.get_text(strip=True).lower()
            if any(kw in button_text for kw in cta_keywords):
                page_data['cta_buttons'].append(button.get_text(strip=True)[:50])
        
        # --- LINK ANALYSIS ---
        for link in soup.find_all("a", href=True):
            absolute = urljoin(url, link['href'])
            anchor_text = link.get_text(strip=True)
            
            # Internal links
            if urlparse(absolute).netloc == domain:
                links.add(normalize_url(absolute))
                if anchor_text:
                    page_data['anchor_texts'].append(anchor_text[:50])
                
                # Check for broken links (quick check)
                try:
                    link_res = requests.head(absolute, timeout=3, allow_redirects=True)
                    if link_res.status_code == 404:
                        page_data['broken_links'].append(absolute)
                except:
                    pass
        
        # --- FORMS & ACCESSIBILITY ---
        for form in soup.find_all("form"):
            fields = form.find_all(['input', 'textarea', 'select'])
            fields_without_labels = 0
            for field in fields:
                if field.get('type') not in ['hidden', 'submit', 'button']:
                    field_id = field.get('id')
                    if field_id and not soup.find('label', attrs={'for': field_id}):
                        fields_without_labels += 1
            
            if len(fields) > 0:
                forms_found.append({
                    "Page URL": url, 
                    "Form Action": form.get('action', 'None'), 
                    "Fields Count": len(fields),
                    "Fields Without Labels": fields_without_labels
                })
                page_data['forms_without_labels'] += fields_without_labels
        
        # Images without alt text
        images = soup.find_all('img')
        page_data['images_without_alt'] = sum(1 for img in images if not img.get('alt'))
        
        # Find Integrations
        for name, patterns in integration_patterns.items():
            if any(re.search(p, all_text, re.I) for p in patterns):
                integrations_found.add(name)
                
        # Find Calculators
        if any(kw in all_text.lower() for kw in ['calculate', 'calculator', 'estimate', 'mortgage', 'bmi']):
            has_calculator = True

        del res, soup, all_text 

    except Exception as e:
        pass

    return url, links, integrations_found, forms_found, has_calculator, page_data

# -----------------------------
# 4. PARALLEL CRAWLER
# -----------------------------
def crawl_site(start_url, max_workers=15, max_pages=5000):
    domain = urlparse(start_url).netloc
    start_url = normalize_url(start_url)
    
    visited = set()
    queued = {start_url} 
    edges = []
    queue = [start_url]
    
    all_integrations = defaultdict(set)
    all_forms = []
    calc_pages = []
    all_page_data = []
    
    integration_patterns = {
        'Google Analytics': [r'google-analytics\.com', r'googletagmanager\.com'],
        'Facebook Pixel': [r'facebook\.com/tr', r'connect\.facebook\.net'],
        'Hotjar': [r'hotjar\.com'], 'Intercom': [r'intercom\.io'],
        'HubSpot': [r'hubspot\.com'], 'Mailchimp': [r'mailchimp\.com'],
        'Zendesk': [r'zdassets\.com'], 'LiveChat': [r'livechatinc\.com'],
        'Stripe': [r'stripe\.com'], 'PayPal': [r'paypal\.com']
    }
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    while queue and len(visited) < max_pages:
        batch = queue[:max_workers]
        queue = queue[max_workers:]
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(fetch_and_analyze, u, domain, integration_patterns) for u in batch]
            
            for future in as_completed(futures):
                url, links, integrations, forms, has_calc, page_data = future.result()
                
                if url in visited: continue
                visited.add(url)
                
                all_page_data.append(page_data)
                
                for name in integrations: all_integrations[name].add(url)
                all_forms.extend(forms)
                if has_calc: calc_pages.append(url)
                
                for link in links:
                    edges.append((url, link))
                    if link not in visited and link not in queued:
                        queued.add(link)
                        queue.append(link)
                        
        progress = min(len(visited) / max_pages, 1.0)
        progress_bar.progress(progress)
        status_text.text(f"🔄 Crawled Pages: {len(visited)} / {max_pages} | UX/IA Analysis Active")
        
    progress_bar.empty()
