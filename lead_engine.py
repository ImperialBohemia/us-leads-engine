"""
US Local Business Lead Engine v3.0
===================================
Multi-source search engine for finding US businesses with outdated websites.

Sources: DuckDuckGo HTML, Bing, manual CSV import
Pipeline: Search → Filter → Email Extract → Web Audit → SQLite → Excel

Usage:
  python3 lead_engine.py --city "Chicago, IL" --niche "roofing" --pages 3
  python3 lead_engine.py --city "Dallas, TX" --niche "hvac" --pages 5
  python3 lead_engine.py --import contacts.csv
  python3 lead_engine.py --export
  python3 lead_engine.py --stats
"""

import re
import os
import sys
import csv
import json
import time
import sqlite3
import argparse
import urllib.request
import urllib.parse
from datetime import datetime
from bs4 import BeautifulSoup

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'leads.db')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
}

# Domains to skip (aggregators, directories, social media)
SKIP_DOMAINS = {
    'yelp.com', 'yellowpages.com', 'bbb.org', 'angi.com', 'homeadvisor.com',
    'thumbtack.com', 'nextdoor.com', 'facebook.com', 'google.com', 'bing.com',
    'mapquest.com', 'superpages.com', 'porch.com', 'bark.com', 'houzz.com',
    'expertise.com', 'topratedlocal.com', 'manta.com', 'birdeye.com',
    'forbes.com', 'instagram.com', 'twitter.com', 'linkedin.com', 'youtube.com',
    'tiktok.com', 'pinterest.com', 'reddit.com', 'wikipedia.org', 'yelp.ca',
    'amazon.com', 'apple.com', 'microsoft.com', 'angieslist.com',
    'duckduckgo.com', 'startpage.com', 'yahoo.com', 'chamberofcommerce.com',
    'buildzoom.com', 'cloudflare.com', 'godaddy.com', 'wix.com',
    'squarespace.com', 'wordpress.com', 'wordpress.org', 'w3.org',
    'github.com', 'stackoverflow.com', 'trustpilot.com', 'glassdoor.com',
    'indeed.com', 'craigslist.org', 'alignable.com', 'kudzu.com',
    'citysearch.com', 'merchantcircle.com', 'dexknows.com', 'hotfrog.com',
    'local.com', 'showmelocal.com', 'brownbook.net', 'cylex.us.com',
    'finduslocal.com', 'n49.com', 'tupalo.com', 'fyple.com',
}

# Search query templates for finding business websites
SEARCH_QUERIES = [
    '{niche} {city} contact',
    '{niche} contractor {city} website',
    '{niche} company {city} email',
    '{niche} service {city} phone',
    '{niche} repair {city} free estimate',
    'best {niche} {city} reviews',
    'local {niche} {city} near me',
    '{niche} {city} licensed insured',
]


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
            query TEXT DEFAULT '',
            results_found INTEGER DEFAULT 0,
            new_leads INTEGER DEFAULT 0,
            source TEXT DEFAULT 'search',
            scanned_at TEXT DEFAULT (datetime('now'))
        )
    ''')
    conn.commit()
    return conn


def domain_from_url(url):
    """Extract clean domain for deduplication."""
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
            data.get('source', 'search'),
            data.get('scan_city', ''),
            data.get('scan_niche', ''),
        ))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def update_lead_enrichment(conn, domain, data):
    """Update lead with email/audit data after enrichment."""
    c = conn.cursor()
    c.execute('''
        UPDATE leads SET
            email = ?, has_ssl = ?, is_mobile_friendly = ?,
            copyright_year = ?, technology = ?,
            website_age_indicator = ?, status = ?
        WHERE domain = ?
    ''', (
        data.get('email', ''),
        data.get('has_ssl', 0),
        data.get('is_mobile_friendly', -1),
        data.get('copyright_year', ''),
        data.get('technology', ''),
        data.get('website_age_indicator', ''),
        data.get('status', 'NEW'),
        domain,
    ))
    conn.commit()


# ═══════════════════════════════════════════════════════════════
# SEARCH ENGINES (DuckDuckGo HTML + Bing fallback)
# ═══════════════════════════════════════════════════════════════

def fetch_page(url, timeout=10):
    """Safe page download with retry."""
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                # Try gzip decompress
                try:
                    import gzip
                    raw = gzip.decompress(raw)
                except:
                    pass
                # Try multiple encodings
                for enc in ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']:
                    try:
                        return raw.decode(enc)
                    except:
                        continue
                return raw.decode('utf-8', errors='ignore')
        except Exception as e:
            if attempt == 0:
                time.sleep(1)
            else:
                return None
    return None


def is_business_domain(domain):
    """Check if domain looks like a real business website."""
    if not domain:
        return False
    domain = domain.lower().replace('www.', '')
    # Skip known aggregators
    for skip in SKIP_DOMAINS:
        if skip in domain:
            return False
    # Skip if domain is too short or generic
    if len(domain) < 5:
        return False
    # Must have a TLD
    if '.' not in domain:
        return False
    return True


def search_ddg(query, max_results=20):
    """Search DuckDuckGo HTML endpoint for business websites."""
    results = []
    try:
        encoded = urllib.parse.quote_plus(query)
        url = f'https://html.duckduckgo.com/html/?q={encoded}'
        html = fetch_page(url, timeout=15)
        if not html:
            return results

        soup = BeautifulSoup(html, 'html.parser')

        for a in soup.select('a.result__a'):
            href = a.get('href', '')
            title = a.get_text(strip=True)

            # Extract real URL from DDG redirect
            real_url = ''
            if '//duckduckgo.com/l/' in href:
                parsed = urllib.parse.urlparse(href)
                qs = urllib.parse.parse_qs(parsed.query)
                real_url = qs.get('uddg', [''])[0]
            elif href.startswith('http'):
                real_url = href

            if real_url:
                domain = domain_from_url(real_url)
                if is_business_domain(domain):
                    results.append({
                        'url': real_url,
                        'domain': domain,
                        'title': title,
                    })

            if len(results) >= max_results:
                break

    except Exception as e:
        print(f'    ⚠ DDG search error: {e}')

    return results


def search_bing(query, max_results=20):
    """Search Bing for business websites."""
    results = []
    try:
        encoded = urllib.parse.quote_plus(query)
        url = f'https://www.bing.com/search?q={encoded}&count=50'

        import requests
        s = requests.Session()
        s.headers.update(HEADERS)
        r = s.get(url, timeout=15)
        if r.status_code != 200:
            return results

        soup = BeautifulSoup(r.text, 'html.parser')

        for li in soup.select('li.b_algo'):
            a = li.select_one('h2 a')
            if not a:
                continue
            href = a.get('href', '')
            title = a.get_text(strip=True)
            if href.startswith('http'):
                domain = domain_from_url(href)
                if is_business_domain(domain):
                    results.append({
                        'url': href,
                        'domain': domain,
                        'title': title,
                    })

            if len(results) >= max_results:
                break

    except Exception as e:
        print(f'    ⚠ Bing search error: {e}')

    return results


def search_businesses(city, niche, max_queries=4):
    """Run multiple search queries to find business websites."""
    all_domains = {}  # domain -> {url, title}

    queries = SEARCH_QUERIES[:max_queries]

    for i, template in enumerate(queries):
        query = template.format(niche=niche, city=city)
        print(f'  🔍 [{i+1}/{len(queries)}] "{query}"')

        # Try DDG first
        results = search_ddg(query)
        source = 'ddg'

        # Fallback to Bing if DDG returns nothing
        if not results:
            results = search_bing(query)
            source = 'bing'

        new_count = 0
        for r in results:
            if r['domain'] not in all_domains:
                all_domains[r['domain']] = r
                new_count += 1

        print(f'    → {len(results)} results ({new_count} new unique) via {source}')
        time.sleep(1.5)  # Be polite between queries

    return list(all_domains.values())


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
                 'user@', 'support@wix', 'email@', 'webmaster@', 'postmaster@']
    if any(x in email for x in blacklist):
        return None
    if not re.match(r'^[a-z0-9_.+-]+@[a-z0-9-]+\.[a-z]{2,}$', email):
        return None
    return email


def find_emails_from_site(base_url, timeout=7):
    """Crawl business website for contact emails."""
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

        # Emails on homepage
        for m in email_regex.findall(html):
            c = clean_email(m)
            if c:
                emails.add(c)

        # Find contact subpages
        soup = BeautifulSoup(html, 'html.parser')
        contact_keywords = ['contact', 'about', 'reach', 'touch', 'email',
                           'staff', 'team', 'meet', 'connect', 'get-in-touch',
                           'request', 'quote', 'estimate']

        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            text = a.get_text(' ', strip=True).lower()
            if any(k in href or k in text for k in contact_keywords):
                full = urllib.parse.urljoin(base_url, a['href'])
                parsed_full = urllib.parse.urlparse(full)
                parsed_base = urllib.parse.urlparse(base_url)
                # Only follow links on same domain
                if parsed_full.netloc.replace('www.', '') == parsed_base.netloc.replace('www.', ''):
                    if full not in pages_to_check and len(pages_to_check) < 5:
                        pages_to_check.append(full)

    except Exception:
        pass

    # Check contact subpages
    for page in pages_to_check[1:]:
        if page in visited or len(emails) >= 3:
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


# ═══════════════════════════════════════════════════════════════
# PHONE EXTRACTOR
# ═══════════════════════════════════════════════════════════════

def find_phone_from_html(html):
    """Extract US phone numbers from HTML."""
    if not html:
        return ''
    phone_patterns = [
        r'\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}',
        r'\d{3}-\d{3}-\d{4}',
        r'\d{10}',
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
    """Quick website audit: age, SSL, mobile, technology."""
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

        # Copyright year
        yr_matches = re.findall(r'(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?(\d{4})', html_lower)
        if yr_matches:
            result['copyright_year'] = max(yr_matches)

        # Meta viewport → mobile friendly
        result['is_mobile_friendly'] = 1 if 'viewport' in html_lower else 0

        # Phone
        result['phone'] = find_phone_from_html(html)

        # Technology detection
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
        if 'jimdo' in html_lower:
            tech.append('Jimdo')
        if 'shopify' in html_lower:
            tech.append('Shopify')
        if 'webflow' in html_lower:
            tech.append('Webflow')
        if '<table' in html_lower and ('bgcolor' in html_lower or 'cellpadding' in html_lower):
            tech.append('Table-Layout')
        if '<frameset' in html_lower or '<frame ' in html_lower:
            tech.append('Frames')
        if 'bootstrap' in html_lower:
            tech.append('Bootstrap')
        if 'jquery' in html_lower:
            tech.append('jQuery')
        if not tech:
            tech.append('Custom/Static')

        result['technology'] = ', '.join(tech)

        # Age indicator
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

        # No viewport = very old
        if result['is_mobile_friendly'] == 0:
            result['website_age_indicator'] = 'VERY_OLD'

    except Exception:
        pass

    return result


# ═══════════════════════════════════════════════════════════════
# BUSINESS NAME EXTRACTION
# ═══════════════════════════════════════════════════════════════

def extract_business_name(url, search_title=''):
    """Try to extract business name from URL or search title."""
    # From search title: remove common suffixes
    if search_title:
        name = search_title
        # Remove common page title suffixes
        for sep in [' | ', ' - ', ' — ', ' :: ', ' · ']:
            if sep in name:
                parts = name.split(sep)
                name = parts[0].strip()
                break
        # Remove common words
        for suffix in ['Home', 'Contact', 'About', 'Welcome to', 'Official Site']:
            name = name.replace(suffix, '').strip()
        if len(name) > 3:
            return name

    # From domain
    domain = domain_from_url(url)
    if domain:
        # Remove TLD
        name = domain.split('.')[0]
        # Split on hyphens and capitalize
        name = ' '.join(w.capitalize() for w in name.split('-'))
        return name

    return ''


# ═══════════════════════════════════════════════════════════════
# EXCEL EXPORT
# ═══════════════════════════════════════════════════════════════

def export_to_excel(conn, filepath=None):
    """Export all leads to formatted Excel."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        os.system('pip install openpyxl --break-system-packages -q')
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

    # ---- Sheet 1: ALL LEADS ----
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
        left=Side(style='thin', color='CCCCCC'),
        right=Side(style='thin', color='CCCCCC'),
        top=Side(style='thin', color='CCCCCC'),
        bottom=Side(style='thin', color='CCCCCC')
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
        is_old = row[16] in ('VERY_OLD', 'OLD')

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

    # ---- Sheet 2: HOT LEADS ----
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

    # ---- Sheet 3: STATS ----
    ws3 = wb.create_sheet('📊 Stats')
    stats = [
        ('Total Leads Found', len(rows)),
        ('With Email', sum(1 for r in rows if r[3])),
        ('Without Email', sum(1 for r in rows if not r[3])),
        ('Very Old Website', sum(1 for r in rows if r[16] == 'VERY_OLD')),
        ('Old Website', sum(1 for r in rows if r[16] == 'OLD')),
        ('Aging Website', sum(1 for r in rows if r[16] == 'AGING')),
        ('Recent Website', sum(1 for r in rows if r[16] == 'RECENT')),
        ('🔥 HOT (Email + Old/VeryOld)', sum(1 for r in rows if r[3] and r[16] in ('VERY_OLD', 'OLD'))),
        ('No SSL', sum(1 for r in rows if r[12] == 0)),
        ('Not Mobile Friendly', sum(1 for r in rows if r[13] == 0)),
    ]

    # Niche breakdown
    niche_counts = {}
    for r in rows:
        n = r[2] or 'Unknown'
        niche_counts[n] = niche_counts.get(n, 0) + 1

    stats_fill = PatternFill(start_color='E8F5E9', end_color='E8F5E9', fill_type='solid')
    for i, (label, val) in enumerate(stats, 1):
        ws3.cell(row=i, column=1, value=label).font = Font(bold=True)
        ws3.cell(row=i, column=2, value=val)

    # Niche breakdown section
    row_offset = len(stats) + 2
    ws3.cell(row=row_offset, column=1, value='NICHE BREAKDOWN').font = Font(bold=True, size=12)
    for i, (niche, count) in enumerate(sorted(niche_counts.items(), key=lambda x: -x[1]), row_offset + 1):
        ws3.cell(row=i, column=1, value=niche)
        ws3.cell(row=i, column=2, value=count)

    ws3.column_dimensions['A'].width = 32
    ws3.column_dimensions['B'].width = 10

    wb.save(filepath)
    print(f'\n✅ Excel exported: {filepath}')
    print(f'   📊 Total: {len(rows)} | With email: {sum(1 for r in rows if r[3])} | 🔥 Hot: {len(hot_rows)}')
    return filepath


# ═══════════════════════════════════════════════════════════════
# CSV IMPORT
# ═══════════════════════════════════════════════════════════════

def import_csv(conn, filepath):
    """Import leads from CSV file."""
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        imported = 0
        for row in reader:
            data = {
                'business_name': row.get('business_name', row.get('name', row.get('Business Name', ''))),
                'website': row.get('website', row.get('url', row.get('Website', ''))),
                'email': row.get('email', row.get('Email', '')),
                'phone': row.get('phone', row.get('Phone', '')),
                'address': row.get('address', row.get('Address', '')),
                'niche': row.get('niche', row.get('industry', row.get('Niche', ''))),
                'source': 'csv_import',
            }
            if data['website'] and insert_lead(conn, data):
                imported += 1

    print(f'✅ Imported {imported} leads from {filepath}')
    return imported


# ═══════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════

def run_scan(city, niche, max_queries=4):
    """Full scan pipeline: Search → Visit → Email → Audit → DB → Excel."""
    conn = init_db()

    print(f'\n{"="*60}')
    print(f'🔍 SCAN: {niche.upper()} in {city.upper()}')
    print(f'{"="*60}')

    # Step 1: Search for business websites
    print(f'\n── Step 1: Searching for business websites ──')
    search_results = search_businesses(city, niche, max_queries)
    print(f'\n  📋 Found {len(search_results)} unique business domains')

    if not search_results:
        print('  ⚠ No results found. Try different niche/city.')
        conn.close()
        return

    # Step 2: Visit each site, extract email, audit
    print(f'\n── Step 2: Enriching leads (email + audit) ──')
    total_new = 0
    total_with_email = 0
    total_hot = 0

    for i, biz in enumerate(search_results):
        domain = biz['domain']
        url = biz['url']
        title = biz.get('title', '')

        # Skip if already in DB
        if is_already_in_db(conn, domain):
            print(f'  ⏭ [{i+1}/{len(search_results)}] {domain} — already in DB')
            continue

        business_name = extract_business_name(url, title)
        print(f'  🔎 [{i+1}/{len(search_results)}] {business_name} → {domain}')

        # Extract emails
        emails = find_emails_from_site(url)
        email = emails[0] if emails else ''

        if email:
            print(f'       ✅ EMAIL: {email}')
            total_with_email += 1
        else:
            print(f'       ❌ No email found')

        # Audit website
        audit = audit_website(url)
        phone = audit.pop('phone', '')

        age = audit.get('website_age_indicator', '')
        mobile = '📱' if audit.get('is_mobile_friendly') == 1 else '🚫📱'
        ssl = '🔒' if audit.get('has_ssl') else '⚠️'
        tech = audit.get('technology', '')
        print(f'       {ssl} {mobile} | Age: {age} | Tech: {tech} | ©{audit.get("copyright_year", "?")}')

        # Determine status
        status = 'NEW'
        if email and age in ('VERY_OLD', 'OLD'):
            status = 'HOT_LEAD'
            total_hot += 1
            print(f'       🔥🔥🔥 HOT LEAD!')
        elif email and age == 'AGING':
            status = 'WARM_LEAD'
        elif email:
            status = 'EMAIL_FOUND'
        elif age in ('VERY_OLD', 'OLD'):
            status = 'OLD_NO_EMAIL'
        else:
            status = 'NO_EMAIL'

        # Save to DB
        lead_data = {
            'business_name': business_name,
            'niche': niche,
            'website': url,
            'email': email,
            'phone': phone,
            'city': city.split(',')[0].strip() if ',' in city else city,
            'state': city.split(',')[1].strip() if ',' in city else '',
            'scan_city': city,
            'scan_niche': niche,
            'source': 'search',
            'status': status,
            **audit,
        }

        if insert_lead(conn, lead_data):
            total_new += 1

        # Be polite
        time.sleep(0.5)

    # Log scan
    c = conn.cursor()
    c.execute('INSERT INTO scan_log (city, niche, results_found, new_leads, source) VALUES (?, ?, ?, ?, ?)',
              (city, niche, len(search_results), total_new, 'search'))
    conn.commit()

    print(f'\n{"="*60}')
    print(f'📊 SCAN RESULTS')
    print(f'   City:         {city}')
    print(f'   Niche:        {niche}')
    print(f'   Domains found:{len(search_results)}')
    print(f'   New in DB:    {total_new}')
    print(f'   With email:   {total_with_email}')
    print(f'   🔥 Hot leads: {total_hot}')
    print(f'{"="*60}\n')

    # Auto-export
    export_to_excel(conn)
    conn.close()


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='US Local Business Lead Engine v3.0')
    parser.add_argument('--city', type=str, help='City and state (e.g. "Chicago, IL")')
    parser.add_argument('--niche', type=str, help='Industry niche (e.g. "roofing", "hvac")')
    parser.add_argument('--pages', type=int, default=4, help='Number of search queries (default: 4)')
    parser.add_argument('--export', action='store_true', help='Export DB to Excel')
    parser.add_argument('--stats', action='store_true', help='Show DB stats')
    parser.add_argument('--import-csv', type=str, dest='import_csv_file', help='Import leads from CSV')

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
        c.execute("SELECT DISTINCT scan_city || ' / ' || scan_niche FROM leads WHERE scan_city != ''")
        scans = [r[0] for r in c.fetchall()]
        print(f'📊 DB Stats: {total} leads | {with_email} with email | {hot} HOT')
        print(f'   Scanned: {", ".join(scans) if scans else "none"}')
        conn.close()
        return

    if args.import_csv_file:
        conn = init_db()
        import_csv(conn, args.import_csv_file)
        conn.close()
        return

    if not args.city or not args.niche:
        parser.print_help()
        print('\nExamples:')
        print('  python3 lead_engine.py --city "Chicago, IL" --niche "roofing" --pages 4')
        print('  python3 lead_engine.py --city "Dallas, TX" --niche "hvac"')
        print('  python3 lead_engine.py --city "Tampa, FL" --niche "plumbing"')
        print('  python3 lead_engine.py --export')
        print('  python3 lead_engine.py --import-csv contacts.csv')
        return

    run_scan(args.city, args.niche, args.pages)


if __name__ == '__main__':
    main()
