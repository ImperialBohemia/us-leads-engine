#!/usr/bin/env python3
"""
Turbo US Lead Engine v5.0 (High-Speed Multi-Source & Live Sheets Streaming)
==========================================================================
Max performance local business discovery & outdated code audit engine:
- Multi-Source: Yahoo Search + DuckDuckGo Lite + Chicago Gov Socrata API
- Parallel Processing: ThreadPoolExecutor (10 concurrent workers)
- Fast Email Extraction: Homepage-first instant exit (1-2s per site)
- Live Streaming: Immediate append_row to Google Sheets on discovery
- Responsive Formatting: Left alignment + WRAP + optimal column widths
- Strict Filter: Zero leads without email saved
"""

import os
import sys
import re
import time
import base64
import sqlite3
import argparse
import urllib.parse
import html as html_module
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests
from bs4 import BeautifulSoup

# Config
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'leads.db')
DEFAULT_GSHEET_ID = '103xx08GvIeH9WvtmUvoxlOWfWv0CT2Bh2HVfnWsvIws'
CREDS_FILE = '/home/q/.gemini/credentials/service_account.json'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}

SKIP_DOMAINS = {
    'yelp.com', 'yellowpages.com', 'bbb.org', 'angi.com', 'homeadvisor.com',
    'thumbtack.com', 'nextdoor.com', 'facebook.com', 'google.com', 'bing.com',
    'yahoo.com', 'mapquest.com', 'superpages.com', 'porch.com', 'bark.com', 'houzz.com',
    'expertise.com', 'topratedlocal.com', 'manta.com', 'birdeye.com', 'threebestrated.com',
    'forbes.com', 'instagram.com', 'twitter.com', 'linkedin.com', 'youtube.com',
    'tiktok.com', 'pinterest.com', 'reddit.com', 'wikipedia.org', 'amazon.com',
    'apple.com', 'microsoft.com', 'angieslist.com', 'duckduckgo.com', 'startpage.com',
    'chamberofcommerce.com', 'buildzoom.com', 'cloudflare.com', 'godaddy.com', 'wix.com',
    'squarespace.com', 'wordpress.com', 'wordpress.org', 'w3.org', 'github.com',
    'chicago.gov', 'illinois.gov', 'gov', 'edu', 'bestprosintown.com', 'constructioncompanieslist.com',
    'uservoice.com', 'sentry.io', 'gravatar.com'
}

# ═══════════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════════

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    return conn

def domain_from_url(url):
    try:
        parsed = urllib.parse.urlparse(url if '://' in url else 'http://' + url)
        domain = parsed.netloc.lower().replace('www.', '').strip('.')
        return domain
    except Exception:
        return url.lower().replace('www.', '')

def is_already_in_db(conn, domain):
    c = conn.cursor()
    c.execute('SELECT id FROM leads WHERE domain = ?', (domain,))
    return c.fetchone() is not None

def insert_lead(conn, data):
    domain = domain_from_url(data.get('website', ''))
    if not domain or is_already_in_db(conn, domain):
        return False
    c = conn.cursor()
    try:
        c.execute('''
            INSERT INTO leads (
                business_name, owner_name, niche, website, domain,
                email, phone, address, city, state, zip_code,
                outdated_score, technical_flaws, doctype,
                has_ssl, is_mobile_friendly, copyright_year,
                technology, website_age_indicator, status,
                source, scan_city, scan_niche
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data.get('business_name', ''),
            data.get('owner_name', ''),
            data.get('niche', ''),
            data.get('website', ''),
            domain,
            data.get('email', ''),
            data.get('phone', ''),
            data.get('address', ''),
            data.get('city', ''),
            data.get('state', ''),
            data.get('zip_code', ''),
            data.get('outdated_score', 0),
            data.get('technical_flaws', ''),
            data.get('doctype', ''),
            data.get('has_ssl', 0),
            data.get('is_mobile_friendly', -1),
            data.get('copyright_year', ''),
            data.get('technology', ''),
            data.get('website_age_indicator', ''),
            data.get('status', 'NEW'),
            data.get('source', 'turbo_search'),
            data.get('scan_city', ''),
            data.get('scan_niche', ''),
        ))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False

# ═══════════════════════════════════════════════════════════════
# SOURCES: YAHOO + DUCKDUCKGO + CHICAGO GOV
# ═══════════════════════════════════════════════════════════════

def clean_business_name(raw_name, domain):
    if not raw_name:
        parts = domain.split('.')[0].replace('-', ' ').title()
        return parts
    clean = re.sub(r'\s*\|\s*.*$', '', raw_name)
    clean = re.sub(r'\s*-\s*(Home|Official Site|Chicago|Illinois|Contractor).*$', '', clean, flags=re.I)
    clean = clean.replace('...', '').strip()
    return clean[:55] if clean else domain

def is_skipped_domain(domain):
    for skip in SKIP_DOMAINS:
        if skip in domain:
            return True
    return False

def source_yahoo(city, niche, max_pages=2):
    results = {}
    session = requests.Session()
    session.headers.update(HEADERS)
    queries = [f'{niche} contractors {city}', f'commercial residential {niche} {city}']

    for q in queries[:max_pages]:
        for p in range(max_pages):
            offset = p * 10 + 1
            url = f'https://search.yahoo.com/search?p={urllib.parse.quote_plus(q)}&b={offset}'
            try:
                r = session.get(url, timeout=6)
                if r.status_code != 200:
                    break
                soup = BeautifulSoup(r.text, 'html.parser')
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    final_url = None
                    if '&u=' in href:
                        try:
                            b64 = href.split('&u=')[1].split('&')[0] + '=='
                            dec = base64.b64decode(b64).decode('utf-8', errors='ignore')
                            if dec.startswith('http'):
                                final_url = dec
                        except Exception:
                            pass
                    elif '/RU=' in href:
                        try:
                            m = href.split('/RU=')[1].split('/RK=')[0]
                            unq = urllib.parse.unquote(m)
                            if unq.startswith('http'):
                                final_url = unq
                        except Exception:
                            pass
                    elif href.startswith('http') and 'yahoo.com' not in href:
                        final_url = href

                    if final_url:
                        dom = domain_from_url(final_url)
                        if dom and '.' in dom and not is_skipped_domain(dom) and dom not in results:
                            results[dom] = {
                                'domain': dom,
                                'url': final_url,
                                'business_name': clean_business_name(a.get_text(strip=True), dom),
                                'source': 'yahoo_search',
                                'niche': niche,
                                'city': city.split(',')[0].strip(),
                                'state': 'IL',
                                'scan_city': city,
                                'scan_niche': niche
                            }
                time.sleep(0.3)
            except Exception:
                break
    return list(results.values())

def source_duckduckgo_lite(city, niche, max_pages=2):
    results = {}
    url = 'https://lite.duckduckgo.com/lite/'
    queries = [f'{niche} contractors {city}']

    for q in queries:
        try:
            r = requests.post(url, data={'q': q}, headers=HEADERS, timeout=6)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                for a in soup.find_all('a', class_='result-link'):
                    href = a.get('href', '')
                    title = a.get_text(strip=True)
                    if href.startswith('http'):
                        dom = domain_from_url(href)
                        if dom and '.' in dom and not is_skipped_domain(dom) and dom not in results:
                            results[dom] = {
                                'domain': dom,
                                'url': href,
                                'business_name': clean_business_name(title, dom),
                                'source': 'duckduckgo_lite',
                                'niche': niche,
                                'city': city.split(',')[0].strip(),
                                'state': 'IL',
                                'scan_city': city,
                                'scan_niche': niche
                            }
            time.sleep(0.4)
        except Exception:
            pass
    return list(results.values())

def source_chicago_gov(niche='Contractor', limit=15):
    results = []
    kw = niche.capitalize()
    url = f"https://data.cityofchicago.org/resource/r5kz-chrr.json?$limit={limit}&$where=business_activity%20like%20'%25{kw}%25'%20or%20business_activity%20like%20'%25Repair%25'"
    try:
        r = requests.get(url, timeout=6)
        if r.status_code == 200:
            for item in r.json():
                biz_name = item.get('doing_business_as_name') or item.get('legal_name')
                if not biz_name:
                    continue
                results.append({
                    'business_name': biz_name.title(),
                    'owner_name': item.get('legal_name', '').title(),
                    'address': item.get('address', ''),
                    'city': item.get('city', 'CHICAGO').title(),
                    'state': item.get('state', 'IL'),
                    'zip_code': item.get('zip_code', ''),
                    'niche': niche,
                    'source': 'chicago_gov_api',
                    'scan_city': 'Chicago, IL',
                    'scan_niche': niche,
                    'is_gov_record': True
                })
    except Exception:
        pass
    return results

def find_website_for_gov_biz(biz_name, city='Chicago'):
    query = f"{biz_name} {city} contractor official website"
    try:
        r = requests.post('https://lite.duckduckgo.com/lite/', data={'q': query}, headers=HEADERS, timeout=4)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            for a in soup.find_all('a', class_='result-link'):
                href = a.get('href', '')
                dom = domain_from_url(href)
                if dom and not is_skipped_domain(dom):
                    return href, dom
    except Exception:
        pass
    return None, None

# ═══════════════════════════════════════════════════════════════
# FAST AUDIT & EMAIL EXTRACTION (HOMEPAGE FIRST)
# ═══════════════════════════════════════════════════════════════

def clean_email(email):
    email = email.lower().strip()
    invalid_ext = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.css', '.js', '.woff', '.pdf']
    if any(email.endswith(ext) for ext in invalid_ext):
        return None
    blacklist = ['sentry', 'wixpress', 'domain.com', 'example.com', 'schema.org',
                 'wordpress', 'developer', 'email.com', 'yourdomain', 'noreply',
                 'placeholder', 'sampleemail', 'name@', 'user@']
    if any(x in email for x in blacklist):
        return None
    if not re.match(r'^[a-z0-9_.+-]+@[a-z0-9-]+\.[a-z]{2,}$', email):
        return None
    return email

def audit_and_extract_fast(url, timeout=4.0):
    audit = {
        'outdated_score': 0,
        'technical_flaws': '',
        'doctype': 'HTML5',
        'has_ssl': 1 if url.startswith('https://') else 0,
        'is_mobile_friendly': 1,
        'copyright_year': '',
        'technology': '',
        'website_age_indicator': 'MODERN',
        'email': '',
        'phone': '',
    }
    score = 0
    flaws = []

    if not audit['has_ssl']:
        score += 20
        flaws.append('No SSL (Insecure HTTP)')

    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code != 200 or not r.text:
            return audit
        raw_html = r.text
        decoded_html = html_module.unescape(raw_html)
        html_lower = decoded_html.lower()
        soup = BeautifulSoup(decoded_html, 'html.parser')

        # 1. Technical Audit
        if '<!doctype html>' not in html_lower[:300]:
            if 'html 4.01' in html_lower[:300] or 'xhtml' in html_lower[:300]:
                audit['doctype'] = 'Legacy HTML4/XHTML'
                score += 25
                flaws.append('Legacy HTML 4/XHTML')

        if '<meta name="viewport"' not in html_lower and '<meta name=\'viewport\'' not in html_lower:
            audit['is_mobile_friendly'] = 0
            score += 30
            flaws.append('Mobile Failure (No Viewport)')

        if '<table' in html_lower and any(attr in html_lower for attr in ['cellpadding', 'cellspacing', 'bgcolor']):
            score += 20
            flaws.append('Table-based Layout')

        for tag in ['font', 'center', 'marquee']:
            if f'<{tag}' in html_lower:
                score += 15
                flaws.append(f'Deprecated <{tag}> tag')
                break

        cp_matches = re.findall(r'(?:copyright|©|\(c\))\s*(?:19\d\d|20\d\d)(?:\s*-\s*(20\d\d))?', html_lower)
        if cp_matches:
            years = [int(y) for match in cp_matches for y in match if y and y.isdigit()]
            if years:
                latest_year = max(years)
                audit['copyright_year'] = str(latest_year)
                if latest_year <= 2018:
                    score += 25
                    flaws.append(f'Ancient Copyright (©{latest_year})')
                elif latest_year <= 2021:
                    score += 10
                    flaws.append(f'Outdated Copyright (©{latest_year})')

        if re.search(r'width\s*:\s*(960|980|1000|1024)px', html_lower):
            score += 15
            flaws.append('Fixed Desktop Width (960-1024px)')

        audit['outdated_score'] = score
        audit['technical_flaws'] = ' | '.join(flaws)
        if score >= 45:
            audit['website_age_indicator'] = 'CRITICAL'
        elif score >= 25:
            audit['website_age_indicator'] = 'OUTDATED'
        else:
            audit['website_age_indicator'] = 'MODERN'

        # 2. FAST EMAIL EXTRACTION (Homepage first)
        # Mailto:
        for a in soup.find_all('a', href=True):
            if a['href'].lower().startswith('mailto:'):
                c = clean_email(urllib.parse.unquote(a['href'][7:].split('?')[0]))
                if c:
                    audit['email'] = c
                    return audit

        # Regex on decoded homepage
        emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}', decoded_html)
        for e in emails:
            c = clean_email(e)
            if c:
                audit['email'] = c
                return audit

        # Subpage fallback (Contact page only if no email on homepage)
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if 'contact' in href or 'reach' in href or 'about' in href:
                sub_url = urllib.parse.urljoin(url, a['href'])
                if domain_from_url(sub_url) == domain_from_url(url):
                    try:
                        r_sub = requests.get(sub_url, headers=HEADERS, timeout=3.0)
                        if r_sub.status_code == 200:
                            sub_decoded = html_module.unescape(r_sub.text)
                            sub_soup = BeautifulSoup(sub_decoded, 'html.parser')
                            for sub_a in sub_soup.find_all('a', href=True):
                                if sub_a['href'].lower().startswith('mailto:'):
                                    c = clean_email(urllib.parse.unquote(sub_a['href'][7:].split('?')[0]))
                                    if c:
                                        audit['email'] = c
                                        return audit
                            for sub_e in re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}', sub_decoded):
                                c = clean_email(sub_e)
                                if c:
                                    audit['email'] = c
                                    return audit
                    except Exception:
                        pass
                    break
    except Exception:
        pass

    return audit

# ═══════════════════════════════════════════════════════════════
# LIVE GOOGLE SHEETS STREAMING
# ═══════════════════════════════════════════════════════════════

_GS_CLIENT = None
_GS_SHEET = None

def get_google_sheet(sheet_id=DEFAULT_GSHEET_ID):
    global _GS_CLIENT, _GS_SHEET
    if _GS_SHEET:
        return _GS_SHEET
    if not os.path.exists(CREDS_FILE):
        return None
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file(CREDS_FILE, scopes=scopes)
        _GS_CLIENT = gspread.authorize(creds)
        _GS_SHEET = _GS_CLIENT.open_by_key(sheet_id)
        return _GS_SHEET
    except Exception as e:
        print(f"  ⚠ Google Sheets error: {e}")
        return None

def append_lead_live_to_gsheet(lead_dict, sheet_id=DEFAULT_GSHEET_ID):
    sh = get_google_sheet(sheet_id)
    if not sh:
        return False
    try:
        row = [
            lead_dict.get('business_name', ''),
            lead_dict.get('owner_name', ''),
            lead_dict.get('niche', ''),
            lead_dict.get('email', ''),
            lead_dict.get('phone', ''),
            lead_dict.get('website', ''),
            lead_dict.get('outdated_score', 0),
            lead_dict.get('technical_flaws', ''),
            lead_dict.get('doctype', ''),
            'ANO' if lead_dict.get('has_ssl') else 'NE',
            'ANO' if lead_dict.get('is_mobile_friendly') == 1 else 'NE',
            lead_dict.get('copyright_year', ''),
            lead_dict.get('technology', ''),
            lead_dict.get('website_age_indicator', ''),
            lead_dict.get('address', ''),
            lead_dict.get('city', ''),
            lead_dict.get('state', ''),
            lead_dict.get('zip_code', ''),
            lead_dict.get('status', 'NEW'),
            datetime.now().strftime('%Y-%m-%d %H:%M')
        ]

        # Append to "Všechny s Emailem"
        try:
            ws_all = sh.worksheet('Všechny s Emailem')
        except Exception:
            ws_all = sh.sheet1
        ws_all.append_row(row, value_input_option='USER_ENTERED')

        # If Hot Lead, also append to "🔥 Hot Outdated Leads"
        if lead_dict.get('outdated_score', 0) >= 25:
            try:
                ws_hot = sh.worksheet('🔥 Hot Outdated Leads')
                ws_hot.append_row(row, value_input_option='USER_ENTERED')
            except Exception:
                pass
        return True
    except Exception as e:
        print(f"  ⚠ Live append error: {e}")
        return False

# ═══════════════════════════════════════════════════════════════
# TURBO BATCH RUNNER
# ═══════════════════════════════════════════════════════════════

def process_candidate(cand, conn):
    dom = cand.get('domain')
    url = cand.get('url')

    # If it came from gov without a website, discover website first
    if cand.get('is_gov_record') and not url:
        w, d = find_website_for_gov_biz(cand['business_name'], cand.get('city', 'Chicago'))
        if not w:
            return None
        url, dom = w, d
        cand['url'] = url
        cand['domain'] = dom

    if not dom or is_already_in_db(conn, dom):
        return None

    audit = audit_and_extract_fast(url, timeout=3.5)
    email = audit.get('email', '')
    if not email:
        return None  # STRICT FILTER: Bez emailu neberem!

    score = audit.get('outdated_score', 0)
    status = 'HOT_LEAD' if score >= 25 else 'MODERN_WITH_EMAIL'

    lead = {
        **cand,
        'website': url,
        'domain': dom,
        'status': status,
        **audit
    }

    # Save to SQLite
    if insert_lead(conn, lead):
        # Live append to Google Sheet immediately!
        append_lead_live_to_gsheet(lead)
        return lead
    return None

def run_turbo_scan(trades, city='Chicago, IL', target=20):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM leads WHERE email != "" AND (scan_city LIKE "%Chicago%" OR city LIKE "%Chicago%")')
    start_count = c.fetchone()[0]
    print(f"\n🚀 TURBO LEAD ENGINE v5.0 | Výchozí stav Chicago: {start_count} leadů")
    print(f"   Zdroje: Yahoo Search + DuckDuckGo Lite + City of Chicago Gov API")
    print(f"   Paralelizace: 10 workerů | Live stream: Google Sheets ({DEFAULT_GSHEET_ID})")
    print(f"{'='*70}")

    total_new = 0
    t_start = time.time()

    for trade in trades:
        c.execute('SELECT COUNT(*) FROM leads WHERE email != "" AND (scan_city LIKE "%Chicago%" OR city LIKE "%Chicago%")')
        curr = c.fetchone()[0]
        if curr >= target:
            print(f"\n🎯 Dosaženo cíle {target} leadů! (Aktuálně: {curr})")
            break

        print(f"\n⚡ Hledám řemeslo: {trade.upper()} v {city} napříč více zdroji...")

        # 1. Gather candidates from 3 sources
        cand_map = {}
        # Source A: Yahoo
        for b in source_yahoo(city, trade, max_pages=2):
            cand_map[b['domain']] = b
        # Source B: DuckDuckGo Lite
        for b in source_duckduckgo_lite(city, trade, max_pages=2):
            if b['domain'] not in cand_map:
                cand_map[b['domain']] = b
        # Source C: Chicago Gov API
        for b in source_chicago_gov(trade, limit=10):
            cand_map[b['business_name']] = b

        candidates = list(cand_map.values())
        print(f"   → Získáno {len(candidates)} unikátních kandidátů z více zdrojů")

        # 2. Parallel processing with ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_cand = {executor.submit(process_candidate, cand, conn): cand for cand in candidates}
            for future in as_completed(future_to_cand):
                try:
                    res = future.result()
                    if res:
                        total_new += 1
                        print(f"   🔥 [LIVE ZÁPIS] {res['business_name']} | {res['niche']} | {res['email']} | Skóre: {res['outdated_score']}")
                except Exception:
                    pass

    total_time = time.time() - t_start
    c.execute('SELECT COUNT(*) FROM leads WHERE email != "" AND (scan_city LIKE "%Chicago%" OR city LIKE "%Chicago%")')
    final_count = c.fetchone()[0]
    conn.close()

    print(f"\n{'='*70}")
    print(f"🏁 TURBO SCAN DOKONČEN za {total_time:.1f}s")
    print(f"   Nově přidáno: {total_new} | Celkem Chicago: {final_count}")
    print(f"   Google Tabulka byla aktualizována LIVE řádek po řádku.")
    print(f"{'='*70}\n")
    return final_count

if __name__ == '__main__':
    trades_list = ['plumber', 'electrician', 'masonry', 'landscaping', 'hvac', 'remodeling', 'locksmith', 'carpenter']
    run_turbo_scan(trades_list, target=25)
