import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import re
import json
import csv
import io
from collections import defaultdict
import time

# --- THE SCANNER ENGINE ---
class EasyScanner:
    def __init__(self, base_url, max_pages):
        self.base_url = base_url
        self.base_domain = urlparse(base_url).netloc
        self.max_pages = max_pages
        self.visited = set()
        self.results = {'urls': [], 'integrations': defaultdict(list), 'forms': [], 'calculators': []}
        
        self.integration_patterns = {
            'Google Analytics': [r'google-analytics\.com', r'googletagmanager\.com'],
            'Facebook Pixel': [r'facebook\.com/tr', r'connect\.facebook\.net'],
            'Hotjar': [r'hotjar\.com'], 'Intercom': [r'intercom\.io'],
            'HubSpot': [r'hubspot\.com'], 'Mailchimp': [r'mailchimp\.com'],
            'Zendesk': [r'zdassets\.com'], 'LiveChat': [r'livechatinc\.com'],
            'Tawk.to': [r'tawk\.to'], 'Crazy Egg': [r'crazyegg\.com'],
            'Stripe': [r'stripe\.com'], 'PayPal': [r'paypal\.com'],
            'Captcha': [r'recaptcha', r'hcaptcha']
        }
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})

    def get_depth(self, url):
        path = urlparse(url).path.strip('/')
        if not path: return {'url': url, 'depth': 0, 'breadcrumb': 'Home'}
        parts = path.split('/')
        if '.' in parts[-1]: parts[-1] = parts[-1].rsplit('.', 1)[0]
        levels = ['Home'] + [p.replace('-', ' ').title() for p in parts if p]
        return {'url': url, 'depth': len(parts), 'breadcrumb': ' > '.join(levels)}

    def scan_page(self, url):
        if url in self.visited or len(self.visited) >= self.max_pages: return []
        self.visited.add(url)
        try:
            html = self.session.get(url, timeout=10).text
        except: return []
        
        self.results['urls'].append(self.get_depth(url))
        soup = BeautifulSoup(html, 'html.parser')
        all_text = str(soup)
        
        for name, patterns in self.integration_patterns.items():
            if any(re.search(p, all_text, re.I) for p in patterns):
                self.results['integrations'][name].append(url)
                
        for form in soup.find_all('form'):
            fields = [{'type': i.get('type', 'text'), 'name': i.get('name', '')} for i in form.find_all(['input', 'textarea', 'select'])]
            if fields: self.results['forms'].append({'url': url, 'action': form.get('action', ''), 'fields_count': len(fields)})
            
        if any(kw in all_text.lower() for kw in ['calculate', 'calculator', 'estimate', 'mortgage', 'bmi']):
            self.results['calculators'].append({'url': url, 'evidence': 'Keywords found'})

        new_links = []
        for a in soup.find_all('a', href=True):
            full_url = urljoin(url, a['href']).split('#')[0]
            if urlparse(full_url).netloc == self.base_domain and full_url not in self.visited:
                new_links.append(full_url)
        time.sleep(0.2)
        return new_links

    def run(self):
        queue = [self.base_url]
        while queue and len(self.visited) < self.max_pages:
            queue.extend(self.scan_page(queue.pop(0)))
        return self.results

# --- THE WEB APP INTERFACE ---
st.set_page_config(page_title="Org Website Scanner", layout="wide")
st.title("🌐 Organization Website Scanner")
st.markdown("Scan any website to map its URL structure, find third-party integrations, and locate forms/calculators.")

col1, col2 = st.columns([3, 1])
with col1:
    target_url = st.text_input("Enter Website URL", "https://www.mediclinic.ae")
with col2:
    max_pages = st.number_input("Max Pages", min_value=10, max_value=200, value=30)

if st.button("🚀 Start Scan", type="primary"):
    with st.spinner(f"Scanning {target_url}... This may take a minute."):
        scanner = EasyScanner(target_url, max_pages)
        results = scanner.run()
        
    st.success(f"✅ Scan Complete! Analyzed {len(results['urls'])} pages.")
    
    tab1, tab2, tab3, tab4 = st.tabs(["📄 URLs & Depth", "🔌 Integrations", "📝 Forms", "🧮 Calculators"])
    
    with tab1:
        st.dataframe(results['urls'], use_container_width=True)
        # Create CSV for download
        csv_data = io.StringIO()
        w = csv.DictWriter(csv_data, fieldnames=['url', 'depth', 'breadcrumb'])
        w.writeheader(); w.writerows(results['urls'])
        st.download_button("Download URLs CSV", csv_data.getvalue(), "urls_depth.csv", "text/csv")
        
    with tab2:
        st.json(dict(results['integrations']))
        
    with tab3:
        st.dataframe(results['forms'], use_container_width=True)
        
    with tab4:
        st.dataframe(results['calculators'], use_container_width=True)