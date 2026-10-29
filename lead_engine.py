"""
US Local Business Lead Engine v3.1
===================================
Precision multi-source lead engine for finding US businesses with outdated websites.

Search Engine: Yahoo Search (unblocked, direct organic extraction)
Pipeline: Yahoo Search → Filter Aggregators → Visit Sites → Extract Emails/Phones → Web Audit → SQLite DB → Formatted Excel

Usage:
  python3 lead_engine.py --city "Chicago, IL" --niche "roofing" --pages 3
  python3 lead_engine.py --city "Dallas, TX" --niche "hvac" --pages 5
  python3 lead_engine.py --export
  python3 lead_engine.py --stats
"""

import re
import os
import sys
import csv
import json
import time
import base64
import sqlite3
import argparse
import urllib.request
import urllib.parse
from datetime import datetime
from bs4 import BeautifulSoup
import requests

# ═══════════════════════════════════════════════════════════════
# CONFIG & DIRECTORY CONSTANTS
# ═══════════════════════════════════════════════════════════════

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'leads.db')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate',
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
            years_in_business TEXT DEFAULT '',
            rating TEXT DEFAULT '',
            review_count TEXT DEFAULT '',
            website_age_indicator TEXT DEFAULT '',
            has_ssl INTEGER DEFAULT 0,
            is_mobile_friendly INTEGER DEFAULT -1,
            page_speed_score INTEGER DEFAULT -1,
            copyright_year TEXT DEFAULT '',
            technology TEXT DEFAULT '',
            status TEXT DEFAULT 'NEW',
            preview_url TEXT DEFAULT '',
            contacted_at TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            source TEXT DEFAULT 'yahoo',
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
                years_in_business, rating, review_count,
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
            data.get('years_in_business', ''),
            data.get('rating', ''),
            data.get('review_count', ''),
            data.get('has_ssl', 0),
            data.get('is_mobile_friendly', -1),
            data.get('copyright_year', ''),
            data.get('technology', ''),
            data.get('website_age_indicator', ''),
            data.get('status', 'NEW'),
            data.get('source', 'yahoo'),
            data.get('scan_city', ''),
            data.get('scan_niche', ''),
        ))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


# ═══════════════════════════════════════════════════════════════
# YAHOO SEARCH SCRAPER
# ═══════════════════════════════════════════════════════════════

def fetch_page(url, timeout=8):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        return r.text
    except Exception:
        return None


def is_business_domain(domain):
    if not domain or len(domain) < 4 or '.' not in domain:
        return False
    domain = domain.lower().replace('www.', '')
    for skip in SKIP_DOMAINS:
        if skip in domain:
            return False
    return True


def search_yahoo(city, niche, max_pages=3):
    session = requests.Session()
    session.headers.update(HEADERS)
    found_leads = {}

    queries = [
        f'{niche} contractors {city}',
        f'{niche} company {city}',
        f'commercial residential {niche} {city}',
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

                    # Bing ad format
                    if '&u=' in href:
                        try:
                            b64 = href.split('&u=')[1].split('&')[0]
                            b64 += '=' * (-len(b64) % 4)
                            dec = base64.b64decode(b64).decode('utf-8', errors='ignore')
                            if dec.startswith('http'):
                                final_url = dec
                        except:
                            pass

                    # Yahoo redirect /RU=
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
                        if is_business_domain(domain) and domain not in found_leads:
                            name = extract_business_name(final_url, title)
                            found_leads[domain] = {
                                'domain': domain,
                                'url': final_url,
                                'title': title,
                                'business_name': name,
                            }
                            page_found += 1

                print(f'     → Nalezeno {page_found} nových unikátních domén')
                time.sleep(1.0)
            except Exception as e:
                print(f'     ⚠ Chyba Yahoo: {e}')
                break

    return list(found_leads.values())


# ═══════════════════════════════════════════════════════════════
# EMAIL & PHONE EXTRACTOR
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
        html = fetch_page(base_url, timeout=timeout)
        if not html:
            return []

        for m in email_regex.findall(html):
            c = clean_email(m)
            if c:
                emails.add(c)

        soup = BeautifulSoup(html, 'html.parser')
        contact_keywords = ['contact', 'about', 'reach', 'touch', 'email',
                           'quote', 'estimate']

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
            html = fetch_page(page, timeout=timeout)
            if html:
                for m in email_regex.findall(html):
                    c = clean_email(m)
                    if c:
                        emails.add(c)
        except Exception:
            continue

    return list(emails)


def find_phone_from_html(html):
    if not html:
        return ''
    phone_patterns = [
        r'\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}',
        r'\d{3}-\d{3}-\d{4}',
    ]
    for pattern in phone_patterns:
        matches = re.findall(pattern, html)
        for m in matches:
            digits = re.sub(r'\D', '', m)
            if len(digits) == 10 and digits[0] not in ('0', '1'):
                return f'({digits[:3]}) {digits[3:6]}-{digits[6:]}'
    return ''


# ═══════════════════════════════════════════════════════════════
# WEB AUDIT
# ═══════════════════════════════════════════════════════════════

def audit_website(url, timeout=7):
    result = {
        'has_ssl': 0,
        'is_mobile_friendly': -1,
        'copyright_year': '',
        'technology': '',
        'website_age_indicator': '',
        'phone': '',
    }

    if not url:
        return result

    if not url.startswith('http'):
        url = 'http://' + url

    result['has_ssl'] = 1 if url.startswith('https') else 0

    try:
        html = fetch_page(url, timeout=timeout)
        if not html:
            return result

        html_lower = html.lower()

        yr_matches = re.findall(r'(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?(\d{4})', html_lower)
        if yr_matches:
            result['copyright_year'] = max(yr_matches)

        result['is_mobile_friendly'] = 1 if 'viewport' in html_lower else 0
        result['phone'] = find_phone_from_html(html)

        tech = []
        if 'wp-content' in html_lower or 'wordpress' in html_lower:
            tech.append('WordPress')
        if 'wix.com' in html_lower or 'wixsite' in html_lower:
            tech.append('Wix')
        if 'squarespace' in html_lower:
            tech.append('Squarespace')
        if 'godaddy' in html_lower or 'secureserver' in html_lower:
            tech.append('GoDaddy')
        if 'weebly' in html_lower:
            tech.append('Weebly')
        if '<table' in html_lower and ('cellpadding' in html_lower or 'bgcolor' in html_lower):
            tech.append('Table-Layout (archaic)')
        if '<frameset' in html_lower or '<frame ' in html_lower:
            tech.append('Frames (ancient)')
        if 'bootstrap' in html_lower:
            tech.append('Bootstrap')
        if not tech:
            tech.append('Custom/Static')

        result['technology'] = ', '.join(tech)

        cy = result['copyright_year']
        if cy:
            try:
                yr = int(cy)
                if yr <= 2015:
                    result['website_age_indicator'] = 'VERY_OLD'
                elif yr <= 2019:
                    result['website_age_indicator'] = 'OLD'
                elif yr <= 2022:
                    result['website_age_indicator'] = 'AGING'
                else:
                    result['website_age_indicator'] = 'RECENT'
            except:
                pass

        if result['is_mobile_friendly'] == 0:
            result['website_age_indicator'] = 'VERY_OLD'

    except Exception:
        pass

    return result


def extract_business_name(url, search_title=''):
    if search_title:
        name = search_title
        # Remove URLs pasted in title
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

    domain = domain_from_url(url)
    if domain:
        base = domain.split('.')[0]
        # Common word boundaries
        words = re.findall(r'[A-Za-z][a-z]*|[0-9]+', base)
        if words:
            return ' '.join(w.capitalize() for w in words)
        return base.capitalize()
    return ''


# ═══════════════════════════════════════════════════════════════
# EXCEL EXPORT
# ═══════════════════════════════════════════════════════════════

def export_to_excel(conn, filepath=None):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    c = conn.cursor()
    c.execute('''
        SELECT business_name, owner_name, niche, email, phone, website,
               address, city, state, zip_code, years_in_business,
               rating, has_ssl, is_mobile_friendly, copyright_year,
               technology, website_age_indicator, status, preview_url,
               scan_city, scan_niche, created_at
        FROM leads
        ORDER BY
            CASE WHEN email != '' THEN 0 ELSE 1 END,
            CASE website_age_indicator
                WHEN 'VERY_OLD' THEN 0
                WHEN 'OLD' THEN 1
                WHEN 'AGING' THEN 2
                ELSE 3 END,
            created_at DESC
    ''')
    rows = c.fetchall()

    if not filepath:
        filepath = os.path.join(os.path.dirname(DB_PATH),
                               f'leads_export_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx')

    wb = Workbook()

    # Sheet 1: ALL LEADS
    ws = wb.active
    ws.title = 'All Leads'

    headers = [
        'Business Name', 'Owner / Contact', 'Industry / Niche', 'Email', 'Phone',
        'Website', 'Address', 'City', 'State', 'ZIP',
        'Years in Business', 'Rating', 'SSL?', 'Mobile?', 'Copyright Year',
        'Technology', 'Age Indicator', 'Status', 'Preview URL',
        'Scan City', 'Scan Niche', 'Found Date'
    ]

    header_fill = PatternFill(start_color='1B3A4B', end_color='1B3A4B', fill_type='solid')
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

    hot_fill = PatternFill(start_color='FFF3E0', end_color='FFF3E0', fill_type='solid')
    email_font = Font(color='0066CC', underline='single')

    for row_idx, row in enumerate(rows, 2):
        has_email = bool(row[3])
        is_old = row[16] in ('VERY_OLD', 'OLD', 'AGING')

        for col_idx, val in enumerate(row, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.border = thin_border
            cell.alignment = Alignment(vertical='center', wrap_text=True)
            if has_email and is_old:
                cell.fill = hot_fill
            if col_idx == 4 and val:
                cell.font = email_font

    widths = [28, 18, 20, 28, 16, 32, 30, 14, 6, 8, 8, 6, 5, 7, 8, 18, 10, 10, 36, 16, 14, 18]
    for i, w in enumerate(widths, 1):
        col_letter = chr(64 + i) if i <= 26 else 'A' + chr(64 + i - 26)
        ws.column_dimensions[col_letter].width = w

    ws.auto_filter.ref = ws.dimensions
    ws.freeze_panes = 'A2'

    # Sheet 2: 🔥 HOT LEADS
    ws2 = wb.create_sheet('🔥 Hot Leads')
    hot_rows = [r for r in rows if r[3] and r[16] in ('VERY_OLD', 'OLD', 'AGING')]

    hot_fill_header = PatternFill(start_color='D84315', end_color='D84315', fill_type='solid')
    for col_idx, h in enumerate(headers, 1):
        cell = ws2.cell(row=1, column=col_idx, value=h)
        cell.font = Font(bold=True, color='FFFFFF', size=11)
        cell.fill = hot_fill_header
        cell.alignment = Alignment(horizontal='center')

    for row_idx, row in enumerate(hot_rows, 2):
        for col_idx, val in enumerate(row, 1):
            ws2.cell(row=row_idx, column=col_idx, value=val)

    ws2.freeze_panes = 'A2'

    # Sheet 3: 📊 STATS
    ws3 = wb.create_sheet('📊 Stats')
    stats = [
        ('Total Leads Found', len(rows)),
        ('With Email', sum(1 for r in rows if r[3])),
        ('Without Email', sum(1 for r in rows if not r[3])),
        ('Very Old Website (<=2015)', sum(1 for r in rows if r[16] == 'VERY_OLD')),
        ('Old Website (<=2019)', sum(1 for r in rows if r[16] == 'OLD')),
        ('Aging Website (<=2022)', sum(1 for r in rows if r[16] == 'AGING')),
        ('Recent Website (>=2023)', sum(1 for r in rows if r[16] == 'RECENT')),
        ('🔥 HOT (Email + Old/VeryOld)', sum(1 for r in rows if r[3] and r[16] in ('VERY_OLD', 'OLD'))),
        ('No SSL (Insecure HTTP)', sum(1 for r in rows if r[12] == 0)),
        ('Not Mobile Friendly', sum(1 for r in rows if r[13] == 0)),
    ]

    for i, (label, val) in enumerate(stats, 1):
        ws3.cell(row=i, column=1, value=label).font = Font(bold=True)
        ws3.cell(row=i, column=2, value=val)

    ws3.column_dimensions['A'].width = 32
    ws3.column_dimensions['B'].width = 10

    wb.save(filepath)
    print(f'\n✅ Excel exportován: {filepath}')
    print(f'   📊 Celkem: {len(rows)} | S emailem: {sum(1 for r in rows if r[3])} | 🔥 Hot: {len(hot_rows)}')
    return filepath


# ═══════════════════════════════════════════════════════════════
# PIPELINE
# ═══════════════════════════════════════════════════════════════

def run_scan(city, niche, max_pages=3):
    conn = init_db()

    print(f'\n{"="*60}')
    print(f'🔍 Skenuji trh: {niche.upper()} v {city.upper()}')
    print(f'{"="*60}')

    # Krok 1: Vyhledávání domén
    print(f'\n── Krok 1: Sběr domén přes Yahoo Search ──')
    raw_leads = search_yahoo(city, niche, max_pages)
    print(f'\n  📋 Získáno celkem {len(raw_leads)} unikátních domén')

    if not raw_leads:
        print('  ⚠ Žádné domény nenalezeny.')
        conn.close()
        return

    # Krok 2: Obohacení (audit, email, telefon)
    print(f'\n── Krok 2: Hledání emailů & audit webů ──')
    total_new = 0
    total_with_email = 0
    total_hot = 0

    for i, biz in enumerate(raw_leads):
        domain = biz['domain']
        url = biz['url']
        name = biz['business_name']

        if is_already_in_db(conn, domain):
            print(f'  ⏭ [{i+1}/{len(raw_leads)}] {domain} — již v DB')
            continue

        print(f'  🔎 [{i+1}/{len(raw_leads)}] {name} ({domain})')

        # Hledání emailu
        emails = find_emails_from_site(url)
        email = emails[0] if emails else ''
        if email:
            print(f'       ✅ EMAIL: {email}')
            total_with_email += 1
        else:
            print(f'       ❌ Email nenalezen')

        # Audit
        audit = audit_website(url)
        phone = audit.pop('phone', '')

        age = audit.get('website_age_indicator', '')
        mobile = '📱' if audit.get('is_mobile_friendly') == 1 else '🚫📱'
        ssl = '🔒' if audit.get('has_ssl') else '⚠️'
        tech = audit.get('technology', '')
        yr = audit.get('copyright_year', '?')

        print(f'       {ssl} {mobile} | Stáří: {age or "RECENT"} | Tech: {tech} | ©{yr}')

        # Status
        status = 'NEW'
        if email and age in ('VERY_OLD', 'OLD'):
            status = 'HOT_LEAD'
            total_hot += 1
            print(f'       🔥🔥🔥 HOT LEAD!')
        elif email:
            status = 'EMAIL_FOUND'
        elif age in ('VERY_OLD', 'OLD'):
            status = 'OLD_NO_EMAIL'

        lead_data = {
            'business_name': name,
            'niche': niche,
            'website': url,
            'email': email,
            'phone': phone,
            'city': city.split(',')[0].strip() if ',' in city else city,
            'state': city.split(',')[1].strip() if ',' in city else '',
            'scan_city': city,
            'scan_niche': niche,
            'source': 'yahoo',
            'status': status,
            **audit,
        }

        if insert_lead(conn, lead_data):
            total_new += 1

        time.sleep(0.4)

    # Log do DB
    c = conn.cursor()
    c.execute('INSERT INTO scan_log (city, niche, results_found, new_leads) VALUES (?, ?, ?, ?)',
              (city, niche, len(raw_leads), total_new))
    conn.commit()

    print(f'\n{"="*60}')
    print(f'📊 VÝSLEDKY SKENU')
    print(f'   Město:         {city}')
    print(f'   Obor:          {niche}')
    print(f'   Nové v DB:     {total_new}')
    print(f'   S emailem:     {total_with_email}')
    print(f'   🔥 Hot Leady:  {total_hot}')
    print(f'{"="*60}\n')

    export_to_excel(conn)
    conn.close()


def main():
    parser = argparse.ArgumentParser(description='US Local Business Lead Engine v3.1')
    parser.add_argument('--city', type=str, help='Město a stát (např. "Chicago, IL")')
    parser.add_argument('--niche', type=str, help='Obor (např. "roofing", "hvac")')
    parser.add_argument('--pages', type=int, default=3, help='Počet dotazů/stránek (výchozí: 3)')
    parser.add_argument('--export', action='store_true', help='Exportovat DB do Excelu')
    parser.add_argument('--stats', action='store_true', help='Statistika DB')

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
        c.execute("SELECT COUNT(*) FROM leads WHERE status = 'HOT_LEAD'")
        hot = c.fetchone()[0]
        print(f'📊 DB Stats: {total} leadů | {with_email} s emailem | {hot} HOT')
        conn.close()
        return

    if not args.city or not args.niche:
        parser.print_help()
        return

    run_scan(args.city, args.niche, args.pages)


if __name__ == '__main__':
    main()
