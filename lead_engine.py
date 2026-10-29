"""
US Local Business Lead Engine v4.0 (Outdated Web Precision Detector)
=====================================================================
Specialized engine for detecting objectively outdated US business websites.

Audit Criteria for Outdated Code:
  1. DOCTYPE: HTML 4.01, XHTML, or Quirks Mode (+25 pts)
  2. Mobile Failure: Missing <meta name="viewport"> (+30 pts)
  3. Archaic Layout: Table-based layout (cellpadding/bgcolor) (+20 pts)
  4. Deprecated Tags: <font>, <center>, <marquee>, <frameset> (+15-30 pts)
  5. Security: No SSL / Insecure HTTP (+20 pts)
  6. Dead Media: Adobe Flash (.swf / shockwave) (+35 pts)
  7. Fixed Width: Hardcoded 960px-1024px desktop container (+15 pts)
  8. Ancient Copyright: <= 2015 (+30 pts), <= 2019 (+20 pts), <= 2022 (+10 pts)
  9. Obsolete Libraries: Ancient jQuery 1.x, FrontPage generator (+15-30 pts)

Data Sources:
  - Source A: Chicago Open Data Portal (Official Licensed Contractors API)
  - Source B: Yahoo Search (organic direct crawling)

Usage:
  python3 lead_engine.py --mode gov --niche "roofing" --limit 30
  python3 lead_engine.py --mode search --city "Chicago, IL" --niche "roofing" --pages 3
  python3 lead_engine.py --export
  python3 lead_engine.py --stats
"""

import re
import os
import sys
import time
import base64
import sqlite3
import argparse
import urllib.parse
from datetime import datetime
from bs4 import BeautifulSoup
import requests

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'leads.db')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Connection': 'keep-alive',
}

SKIP_DOMAINS = {
    'yelp.com', 'yellowpages.com', 'bbb.org', 'angi.com', 'homeadvisor.com',
    'thumbtack.com', 'nextdoor.com', 'facebook.com', 'google.com', 'bing.com',
    'yahoo.com', 'mapquest.com', 'superpages.com', 'porch.com', 'bark.com', 'houzz.com',
    'expertise.com', 'topratedlocal.com', 'manta.com', 'birdeye.com', 'threebestrated.com',
    'forbes.com', 'instagram.com', 'twitter.com', 'linkedin.com', 'youtube.com',
    'tiktok.com', 'pinterest.com', 'reddit.com', 'wikipedia.org', 'yelp.ca',
    'amazon.com', 'apple.com', 'microsoft.com', 'angieslist.com',
    'duckduckgo.com', 'startpage.com', 'chamberofcommerce.com',
    'buildzoom.com', 'cloudflare.com', 'godaddy.com', 'wix.com',
    'squarespace.com', 'wordpress.com', 'wordpress.org', 'w3.org',
    'github.com', 'stackoverflow.com', 'trustpilot.com', 'glassdoor.com',
    'indeed.com', 'craigslist.org', 'alignable.com', 'kudzu.com',
    'citysearch.com', 'merchantcircle.com', 'dexknows.com', 'hotfrog.com',
    'local.com', 'showmelocal.com', 'brownbook.net', 'cylex.us.com',
    'finduslocal.com', 'n49.com', 'tupalo.com', 'fyple.com', 'here.com',
    'roof.info', 'crca.org', 'ontoplist.com', 'uservoice.com', 'guce.yahoo.com',
    'chicago.gov', 'illinois.gov', 'gov', 'edu',
}


# ═══════════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════════

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_name TEXT,
            owner_name TEXT DEFAULT '',
            niche TEXT,
            website TEXT UNIQUE,
            domain TEXT UNIQUE,
            email TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            address TEXT DEFAULT '',
            city TEXT DEFAULT '',
            state TEXT DEFAULT '',
            zip_code TEXT DEFAULT '',
            outdated_score INTEGER DEFAULT 0,
            technical_flaws TEXT DEFAULT '',
            doctype TEXT DEFAULT '',
            has_ssl INTEGER DEFAULT 0,
            is_mobile_friendly INTEGER DEFAULT -1,
            copyright_year TEXT DEFAULT '',
            technology TEXT DEFAULT '',
            website_age_indicator TEXT DEFAULT '',
            status TEXT DEFAULT 'NEW',
            preview_url TEXT DEFAULT '',
            contacted_at TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            source TEXT DEFAULT 'search',
            scan_city TEXT DEFAULT '',
            scan_niche TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS scan_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city TEXT,
            niche TEXT,
            results_found INTEGER DEFAULT 0,
            new_leads INTEGER DEFAULT 0,
            hot_leads INTEGER DEFAULT 0,
            source TEXT DEFAULT 'search',
            scanned_at TEXT DEFAULT (datetime('now'))
        )
    ''')
    conn.commit()
    return conn


def domain_from_url(url):
    try:
        parsed = urllib.parse.urlparse(url if '://' in url else 'http://' + url)
        domain = parsed.netloc.lower().replace('www.', '').strip('.')
        return domain
    except:
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
            data.get('source', 'search'),
            data.get('scan_city', ''),
            data.get('scan_niche', ''),
        ))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


# ═══════════════════════════════════════════════════════════════
# ADVANCED OUTDATED CODE AUDIT ENGINE
# ═══════════════════════════════════════════════════════════════

def fetch_page(url, timeout=8):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        return r.text, r.url
    except Exception:
        return None, url


def audit_website_code(url, timeout=8):
    """
    Rigorously detects whether a website uses archaic or outdated web code.
    Returns score (0-100+), technical flaws list, and specific indicators.
    """
    audit = {
        'outdated_score': 0,
        'technical_flaws': '',
        'doctype': 'HTML5',
        'has_ssl': 0,
        'is_mobile_friendly': 1,
        'copyright_year': '',
        'technology': '',
        'website_age_indicator': 'MODERN',
        'phone': '',
    }

    if not url:
        return audit

    if not url.startswith('http'):
        url = 'http://' + url

    html, final_url = fetch_page(url, timeout=timeout)
    if not html:
        return audit

    html_lower = html.lower()
    flaws = []
    score = 0

    # 1. SSL / Security check
    if final_url.startswith('https://'):
        audit['has_ssl'] = 1
    else:
        score += 20
        flaws.append('No SSL (Insecure HTTP)')

    # 2. DOCTYPE analysis (Quirks vs Standards)
    snippet_start = html_lower[:300]
    if '<!doctype html>' in snippet_start:
        audit['doctype'] = 'HTML5'
    elif 'html 4.01 transitional' in snippet_start:
        audit['doctype'] = 'HTML 4.01 Transitional'
        score += 25
        flaws.append('Archaic HTML 4.01 DOCTYPE')
    elif 'xhtml 1.0' in snippet_start:
        audit['doctype'] = 'XHTML 1.0'
        score += 20
        flaws.append('Old XHTML 1.0 DOCTYPE')
    elif '<!doctype' not in snippet_start:
        audit['doctype'] = 'Missing DOCTYPE'
        score += 25
        flaws.append('Missing DOCTYPE (Quirks Mode)')

    # 3. Mobile responsiveness (<meta name="viewport">)
    if 'name="viewport"' in html_lower or "name='viewport'" in html_lower:
        audit['is_mobile_friendly'] = 1
    else:
        audit['is_mobile_friendly'] = 0
        score += 30
        flaws.append('No Mobile Viewport (Unresponsive)')

    # 4. Archaic HTML structure & tags
    if re.search(r'<table[^>]+(cellpadding|cellspacing|bgcolor)', html_lower):
        score += 20
        flaws.append('Table-Layout Structure')
    if '<font ' in html_lower or '<font>' in html_lower:
        score += 20
        flaws.append('Deprecated <font> Tags')
    if '<center' in html_lower:
        score += 15
        flaws.append('Deprecated <center> Tags')
    if '<frameset' in html_lower or '<frame ' in html_lower:
        score += 30
        flaws.append('Ancient HTML Framesets')
    if '.swf' in html_lower or 'application/x-shockwave-flash' in html_lower:
        score += 35
        flaws.append('Dead Flash Content (.swf)')

    # 5. Fixed desktop width layouts (960px / 980px / 1024px)
    if re.search(r'width\s*[:=]\s*["\']?(960|980|1000|1024)px?["\']?', html_lower):
        score += 15
        flaws.append('Fixed Desktop Width (960-1024px)')

    # 6. Copyright year analysis
    years = re.findall(r'(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?(\d{4})', html_lower)
    if years:
        latest = int(max(years))
        audit['copyright_year'] = str(latest)
        if latest <= 2015:
            score += 30
            flaws.append(f'Ancient Copyright (©{latest})')
        elif latest <= 2019:
            score += 20
            flaws.append(f'Outdated Copyright (©{latest})')
        elif latest <= 2022:
            score += 10
            flaws.append(f'Aging Copyright (©{latest})')

    # 7. Archaic JS and Libraries
    tech = []
    jq_match = re.search(r'jquery[-.](1\.[0-9]+(?:\.[0-9]+)?)', html_lower)
    if jq_match:
        ver = jq_match.group(1)
        tech.append(f'jQuery {ver}')
        score += 15
        flaws.append(f'Ancient jQuery v{ver}')

    if 'wp-content' in html_lower or 'wordpress' in html_lower:
        tech.append('WordPress')
    if 'wix.com' in html_lower:
        tech.append('Wix')
    if 'squarespace' in html_lower:
        tech.append('Squarespace')
    if 'godaddy' in html_lower:
        tech.append('GoDaddy')
    if 'frontpage' in html_lower:
        tech.append('MS FrontPage')
        score += 30
        flaws.append('Built with MS FrontPage')
    if 'bootstrap' in html_lower:
        tech.append('Bootstrap')
    if not tech:
        tech.append('Custom/Static')

    audit['technology'] = ', '.join(tech)

    # 8. Phone extraction
    phone_matches = re.findall(r'\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}', html)
    if phone_matches:
        digits = re.sub(r'\D', '', phone_matches[0])
        if len(digits) == 10 and digits[0] not in ('0', '1'):
            audit['phone'] = f'({digits[:3]}) {digits[3:6]}-{digits[6:]}'

    # Classification & final score
    audit['outdated_score'] = score
    audit['technical_flaws'] = ' | '.join(flaws)

    if score >= 45:
        audit['website_age_indicator'] = 'VERY_OLD_CODE'
    elif score >= 25:
        audit['website_age_indicator'] = 'OUTDATED'
    elif score >= 10:
        audit['website_age_indicator'] = 'AGING'
    else:
        audit['website_age_indicator'] = 'MODERN'

    return audit


# ═══════════════════════════════════════════════════════════════
# EMAIL EXTRACTOR
# ═══════════════════════════════════════════════════════════════

def clean_email(email):
    email = email.lower().strip()
    invalid_ext = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.css', '.js',
                   '.woff', '.ttf', '.pdf', '.zip', '.mp4', '.mp3']
    if any(email.endswith(ext) for ext in invalid_ext):
        return None
    blacklist = ['sentry', 'wixpress', 'domain.com', 'example.com', 'schema.org',
                 'wordpress', 'developer', 'email.com', 'yourdomain', 'your-email',
                 'noreply', 'no-reply', 'changeme', 'test@', 'admin@wordpress',
                 'placeholder', 'sampleemail', 'yourname', 'name@', 'info@example',
                 'user@', 'support@wix', 'webmaster@', 'postmaster@']
    if any(x in email for x in blacklist):
        return None
    if not re.match(r'^[a-z0-9_.+-]+@[a-z0-9-]+\.[a-z]{2,}$', email):
        return None
    return email


def find_emails_from_site(base_url, timeout=7):
    if not base_url:
        return []
    if not base_url.startswith('http'):
        base_url = 'http://' + base_url

    emails = set()
    pages_to_check = [base_url]
    visited = set()
    email_regex = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}')

    try:
        html, _ = fetch_page(base_url, timeout=timeout)
        if not html:
            return []

        for m in email_regex.findall(html):
            c = clean_email(m)
            if c:
                emails.add(c)

        soup = BeautifulSoup(html, 'html.parser')
        contact_keywords = ['contact', 'about', 'reach', 'touch', 'email', 'quote', 'estimate']

        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            text = a.get_text(' ', strip=True).lower()
            if any(k in href or k in text for k in contact_keywords):
                full = urllib.parse.urljoin(base_url, a['href'])
                parsed_full = urllib.parse.urlparse(full)
                parsed_base = urllib.parse.urlparse(base_url)
                if parsed_full.netloc.replace('www.', '') == parsed_base.netloc.replace('www.', ''):
                    if full not in pages_to_check and len(pages_to_check) < 4:
                        pages_to_check.append(full)
    except Exception:
        pass

    for page in pages_to_check[1:]:
        if page in visited or len(emails) >= 2:
            break
        visited.add(page)
        try:
            html, _ = fetch_page(page, timeout=timeout)
            if html:
                for m in email_regex.findall(html):
                    c = clean_email(m)
                    if c:
                        emails.add(c)
        except Exception:
            continue

    return list(emails)


# ═══════════════════════════════════════════════════════════════
# BUSINESS DISCOVERY
# ═══════════════════════════════════════════════════════════════

def clean_business_name(name, domain=''):
    if name:
        name = re.sub(r'https?://\S+', '', name)
        name = re.sub(r'›.*', '', name)
        for sep in [' | ', ' - ', ' — ', ' :: ', ' · ']:
            if sep in name:
                name = name.split(sep)[0].strip()
                break
        for suffix in ['Home', 'Contact', 'About', 'Welcome to', 'Official Site', 'Website']:
            name = name.replace(suffix, '').strip()
        if len(name) > 3 and not name.lower().startswith('http'):
            return name

    if domain:
        base = domain.split('.')[0]
        words = re.findall(r'[A-Za-z][a-z]*|[0-9]+', base)
        if words:
            return ' '.join(w.capitalize() for w in words)
        return base.capitalize()
    return ''


def is_skipped_domain(domain):
    if not domain or len(domain) < 4:
        return True
    domain = domain.lower().replace('www.', '')
    for skip in SKIP_DOMAINS:
        if skip in domain:
            return True
    return False


def search_yahoo_outdated(city, niche, max_pages=3):
    session = requests.Session()
    session.headers.update(HEADERS)
    found_leads = {}

    queries = [
        f'{niche} contractors {city}',
        f'commercial residential {niche} {city}',
        f'{niche} repair {city}',
    ]

    for q_idx, query in enumerate(queries[:max_pages]):
        for p in range(max_pages):
            b_offset = p * 10 + 1
            encoded = urllib.parse.quote_plus(query)
            url = f'https://search.yahoo.com/search?p={encoded}&b={b_offset}'
            print(f'  🔍 Yahoo Search: "{query}" (p.{p+1})')

            try:
                r = session.get(url, timeout=10)
                if r.status_code != 200:
                    break

                soup = BeautifulSoup(r.text, 'html.parser')
                page_found = 0

                for a in soup.find_all('a', href=True):
                    href = a['href']
                    title = a.get_text(strip=True)
                    final_url = None

                    if '&u=' in href:
                        try:
                            b64 = href.split('&u=')[1].split('&')[0]
                            b64 += '=' * (-len(b64) % 4)
                            dec = base64.b64decode(b64).decode('utf-8', errors='ignore')
                            if dec.startswith('http'):
                                final_url = dec
                        except:
                            pass
                    elif '/RU=' in href:
                        try:
                            m = href.split('/RU=')[1].split('/RK=')[0]
                            unq = urllib.parse.unquote(m)
                            if unq.startswith('http'):
                                final_url = unq
                        except:
                            pass
                    elif href.startswith('http') and 'yahoo.com' not in href and 'bing.com' not in href:
                        final_url = href

                    if final_url:
                        domain = domain_from_url(final_url)
                        if domain and '.' in domain and not is_skipped_domain(domain) and domain not in found_leads:
                            name = clean_business_name(title, domain)
                            found_leads[domain] = {
                                'domain': domain,
                                'url': final_url,
                                'business_name': name,
                                'source': 'yahoo_search',
                            }
                            page_found += 1

                print(f'     → Nalezeno {page_found} nových unikátních domén')
                time.sleep(0.8)
            except Exception as e:
                print(f'     ⚠ Chyba: {e}')
                break

    return list(found_leads.values())


def query_chicago_gov_api(niche='roofing', limit=25):
    """Fetch registered licensed businesses from Chicago Open Data Portal."""
    print(f'  🏛 Dotazuji oficiální City of Chicago Data Portal...')
    url = f"https://data.cityofchicago.org/resource/r5kz-chrr.json?$limit={limit}&$where=business_activity like '%Roofing%' or business_activity like '%Home Repair%'"
    try:
        r = requests.get(url, timeout=12)
        if r.status_code != 200:
            return []
        data = r.json()
        leads = []
        for d in data:
            biz_name = d.get('doing_business_as_name') or d.get('legal_name')
            owner = d.get('legal_name', '')
            addr = f"{d.get('address', '')}"
            city = d.get('city', 'CHICAGO')
            state = d.get('state', 'IL')
            zip_code = d.get('zip_code', '')
            leads.append({
                'business_name': biz_name,
                'owner_name': owner,
                'address': addr,
                'city': city,
                'state': state,
                'zip_code': zip_code,
                'niche': niche,
                'source': 'chicago_gov_data',
            })
        print(f'  📋 Získáno {len(leads)} licencovaných firem z vládního registru')
        return leads
    except Exception as e:
        print(f'  ⚠ Chyba API: {e}')
        return []


def find_website_for_business(business_name, city='Chicago'):
    """Find company website via targeted search."""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    query = f"{business_name} {city} contractor website"
    url = f"https://search.yahoo.com/search?p={urllib.parse.quote_plus(query)}"
    try:
        r = requests.get(url, headers=headers, timeout=8)
        soup = BeautifulSoup(r.text, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/RU=' in href:
                try:
                    m = href.split('/RU=')[1].split('/RK=')[0]
                    unq = urllib.parse.unquote(m)
                    dom = domain_from_url(unq)
                    if dom and dom not in SKIP_DOMAINS:
                        return unq
                except:
                    pass
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════════
# EXCEL EXPORT (Focus on Outdated Code & Flaws)
# ═══════════════════════════════════════════════════════════════

def export_to_excel(conn, filepath=None):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    c = conn.cursor()
    c.execute('''
        SELECT business_name, owner_name, niche, email, phone, website,
               outdated_score, technical_flaws, doctype, has_ssl,
               is_mobile_friendly, copyright_year, technology,
               website_age_indicator, address, city, state, zip_code,
               status, created_at
        FROM leads
        ORDER BY
            CASE WHEN email != '' THEN 0 ELSE 1 END,
            outdated_score DESC,
            created_at DESC
    ''')
    rows = c.fetchall()

    if not filepath:
        filepath = os.path.join(os.path.dirname(DB_PATH),
                               f'outdated_leads_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx')

    wb = Workbook()

    # Sheet 1: ALL LEADS
    ws = wb.active
    ws.title = 'Všechny Leady'

    headers = [
        'Firma', 'Majitel / Zástupce', 'Obor', 'Email', 'Telefon', 'Web',
        'Stáří Kódu (0-100)', 'Technické Vady Webu', 'Doctype', 'SSL?',
        'Responzivní?', 'Rok Copyrightu', 'Technologie', 'Kategorie Stáří',
        'Adresa', 'Město', 'Stát', 'ZIP', 'Status', 'Nalezeno'
    ]

    header_fill = PatternFill(start_color='1A2530', end_color='1A2530', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF', size=11)
    thin_border = Border(
        left=Side(style='thin', color='DDDDDD'),
        right=Side(style='thin', color='DDDDDD'),
        top=Side(style='thin', color='DDDDDD'),
        bottom=Side(style='thin', color='DDDDDD')
    )

    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = thin_border

    hot_fill = PatternFill(start_color='FFE0B2', end_color='FFE0B2', fill_type='solid')
    archaic_fill = PatternFill(start_color='FFCDD2', end_color='FFCDD2', fill_type='solid')
    email_font = Font(color='0044CC', underline='single')

    for row_idx, row in enumerate(rows, 2):
        has_email = bool(row[3])
        score = row[6] or 0

        for col_idx, val in enumerate(row, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.border = thin_border
            cell.alignment = Alignment(vertical='center', wrap_text=True)

            if score >= 45 and has_email:
                cell.fill = archaic_fill  # Kriticky zastaralý web s emailem!
            elif score >= 25 and has_email:
                cell.fill = hot_fill

            if col_idx == 4 and val:
                cell.font = email_font

    widths = [26, 20, 16, 26, 16, 32, 18, 36, 16, 6, 8, 8, 16, 14, 24, 12, 6, 8, 12, 16]
    for i, w in enumerate(widths, 1):
        col_letter = chr(64 + i) if i <= 26 else 'A' + chr(64 + i - 26)
        ws.column_dimensions[col_letter].width = w

    ws.auto_filter.ref = ws.dimensions
    ws.freeze_panes = 'A2'

    # Sheet 2: 🔥 HOT LEADS (Email + Outdated Score >= 25)
    ws2 = wb.create_sheet('🔥 Hot Outdated Leads')
    hot_rows = [r for r in rows if r[3] and (r[6] or 0) >= 25]

    hot_fill_header = PatternFill(start_color='D32F2F', end_color='D32F2F', fill_type='solid')
    for col_idx, h in enumerate(headers, 1):
        cell = ws2.cell(row=1, column=col_idx, value=h)
        cell.font = Font(bold=True, color='FFFFFF', size=11)
        cell.fill = hot_fill_header
        cell.alignment = Alignment(horizontal='center')

    for row_idx, row in enumerate(hot_rows, 2):
        for col_idx, val in enumerate(row, 1):
            cell = ws2.cell(row=row_idx, column=col_idx, value=val)
            cell.border = thin_border
            if col_idx == 4 and val:
                cell.font = email_font

    for i, w in enumerate(widths, 1):
        col_letter = chr(64 + i) if i <= 26 else 'A' + chr(64 + i - 26)
        ws2.column_dimensions[col_letter].width = w

    ws2.auto_filter.ref = ws2.dimensions
    ws2.freeze_panes = 'A2'

    # Sheet 3: STATS
    ws3 = wb.create_sheet('📊 Statistiky')
    stats = [
        ('Celkem Prověřeno Webů', len(rows)),
        ('S Nalezeným Emailem', sum(1 for r in rows if r[3])),
        ('Kriticky Zastaralý Kód (Score >= 45)', sum(1 for r in rows if (r[6] or 0) >= 45)),
        ('Zastaralý Web (Score 25-44)', sum(1 for r in rows if 25 <= (r[6] or 0) < 45)),
        ('Moderní Web (Score < 25)', sum(1 for r in rows if (r[6] or 0) < 25)),
        ('🔥 TOP CÍLE (Email + Zastaralý Kód)', len(hot_rows)),
        ('Bez SSL Šifrování (HTTP)', sum(1 for r in rows if r[9] == 0)),
        ('Neresponzivní pro Mobily', sum(1 for r in rows if r[10] == 0)),
    ]

    for i, (label, val) in enumerate(stats, 1):
        ws3.cell(row=i, column=1, value=label).font = Font(bold=True)
        ws3.cell(row=i, column=2, value=val)

    ws3.column_dimensions['A'].width = 36
    ws3.column_dimensions['B'].width = 10

    wb.save(filepath)
    print(f'\n✅ Excel exportován: {filepath}')
    print(f'   📊 Celkem: {len(rows)} | S emailem: {sum(1 for r in rows if r[3])} | 🔥 Hot: {len(hot_rows)}')
    return filepath


# ═══════════════════════════════════════════════════════════════
# EXECUTION MODES
# ═══════════════════════════════════════════════════════════════

def run_pipeline(mode='search', city='Chicago, IL', niche='roofing', limit_or_pages=3):
    conn = init_db()

    print(f'\n{"="*65}')
    print(f'🚀 DETEKCE ZASTARALÝCH WEBŮ | Režim: {mode.upper()} | {niche.upper()} v {city.upper()}')
    print(f'{"="*65}')

    candidates = []

    if mode == 'gov':
        # Režim: Oficiální vládní databáze licencovaných firem Chicaga
        gov_list = query_chicago_gov_api(niche, limit=limit_or_pages)
        for biz in gov_list:
            web = find_website_for_business(biz['business_name'], city=biz['city'])
            if web:
                dom = domain_from_url(web)
                if not is_already_in_db(conn, dom):
                    candidates.append({
                        **biz,
                        'website': web,
                        'domain': dom,
                    })
    else:
        # Režim: Yahoo organické vyhledávání
        raw = search_yahoo_outdated(city, niche, max_pages=limit_or_pages)
        for biz in raw:
            dom = biz['domain']
            if not is_already_in_db(conn, dom):
                candidates.append({
                    'business_name': biz['business_name'],
                    'website': biz['url'],
                    'domain': dom,
                    'niche': niche,
                    'city': city.split(',')[0].strip(),
                    'state': city.split(',')[1].strip() if ',' in city else 'IL',
                    'scan_city': city,
                    'scan_niche': niche,
                    'source': 'yahoo_search',
                })

    print(f'\n── Krok 2: Přísný technický audit kódu & sběr emailů ({len(candidates)} webů) ──')

    total_new = 0
    total_hot = 0

    for i, biz in enumerate(candidates):
        url = biz['website']
        dom = biz['domain']
        name = biz['business_name']

        print(f'\n  🔎 [{i+1}/{len(candidates)}] {name} ({dom})')

        # 1. Detailní audit kódu
        audit = audit_website_code(url)
        score = audit['outdated_score']
        flaws = audit['technical_flaws']
        phone = audit.pop('phone', '')

        print(f'       🎯 Skóre zastaralosti: {score}/100 [{audit["website_age_indicator"]}]')
        if flaws:
            print(f'       ⚠️  Nalezené vady: {flaws}')
        else:
            print(f'       ✨ Moderní kód (žádné kritické vady)')

        # 2. Hledání emailu
        emails = find_emails_from_site(url)
        email = emails[0] if emails else ''

        if email:
            print(f'       📬 Email: {email}')
        else:
            print(f'       ❌ Email nenalezen')

        # 3. Status
        if email and score >= 25:
            status = 'HOT_LEAD'
            total_hot += 1
            print(f'       🔥🔥🔥 HOT PROSPECT!')
        elif score >= 25:
            status = 'OUTDATED_NO_EMAIL'
        elif email:
            status = 'MODERN_WITH_EMAIL'
        else:
            status = 'MODERN_NO_EMAIL'

        lead_record = {
            **biz,
            'email': email,
            'phone': biz.get('phone') or phone,
            'status': status,
            **audit,
        }

        if insert_lead(conn, lead_record):
            total_new += 1

        time.sleep(0.4)

    # Uložit do logu
    c = conn.cursor()
    c.execute('INSERT INTO scan_log (city, niche, results_found, new_leads, hot_leads, source) VALUES (?, ?, ?, ?, ?, ?)',
              (city, niche, len(candidates), total_new, total_hot, mode))
    conn.commit()

    print(f'\n{"="*65}')
    print(f'📊 VÝSLEDKY AUDITU')
    print(f'   Nové weby v DB:      {total_new}')
    print(f'   🔥 Hot Leady (Starý kód + Email): {total_hot}')
    print(f'{"="*65}\n')

    export_to_excel(conn)
    conn.close()


def main():
    parser = argparse.ArgumentParser(description='US Local Business Lead Engine v4.0 (Outdated Web Precision)')
    parser.add_argument('--mode', choices=['search', 'gov'], default='search', help='Režim: search (Yahoo) nebo gov (Chicago Gov API)')
    parser.add_argument('--city', type=str, default='Chicago, IL', help='Město a stát (výchozí: "Chicago, IL")')
    parser.add_argument('--niche', type=str, default='roofing', help='Obor (výchozí: "roofing")')
    parser.add_argument('--pages', type=int, default=3, help='Počet stránek/dotazů (pro search)')
    parser.add_argument('--limit', type=int, default=25, help='Limit firem (pro gov režim)')
    parser.add_argument('--export', action='store_true', help='Exportovat DB do Excelu')
    parser.add_argument('--stats', action='store_true', help='Zobrazit statistiky DB')

    args = parser.parse_args()

    if args.export:
        conn = init_db()
        export_to_excel(conn)
        conn.close()
        return

    if args.stats:
        conn = init_db()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM leads')
        total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM leads WHERE email != ''")
        with_email = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM leads WHERE outdated_score >= 25 AND email != ''")
        hot = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM leads WHERE outdated_score >= 45")
        archaic = c.fetchone()[0]
        print(f'📊 DB Stats: {total} leadů | {with_email} s emailem | {hot} 🔥 HOT | {archaic} 💀 Archaický kód')
        conn.close()
        return

    limit_or_pages = args.limit if args.mode == 'gov' else args.pages
    run_pipeline(args.mode, args.city, args.niche, limit_or_pages)


if __name__ == '__main__':
    main()
