import re
import urllib.request
from urllib.parse import urljoin
from bs4 import BeautifulSoup

def clean_email(email):
    email = email.lower().strip()
    invalid_ext = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.css', '.js', '.woff', '.ttf']
    if any(email.endswith(ext) for ext in invalid_ext):
        return None
    if any(x in email for x in ['sentry', 'wixpress', 'domain.com', 'example.com', 'schema.org']):
        return None
    return email

def find_emails_from_site(base_url, timeout=7):
    """
    Projde hlavní stránku a automaticky detekuje kontaktní odkazy (Contact, About, Kontakty).
    Pokud najde e-mail, vrátí ho.
    """
    emails = set()
    pages_to_check = [base_url]
    visited = set()
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    email_regex = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')

    # 1. Stáhnout homepage a najít odkazy na Contact / About
    try:
        req = urllib.request.Request(base_url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read()
            for enc in ['utf-8', 'cp1250', 'iso-8859-1']:
                try:
                    html = content.decode(enc)
                    break
                except:
                    html = content.decode('utf-8', errors='ignore')

            # Hledat přímo na homepage
            for m in email_regex.findall(html):
                c = clean_email(m)
                if c: emails.add(c)

            # Najít podstránky s kontakty
            soup = BeautifulSoup(html, 'html.parser')
            for a in soup.find_all('a', href=True):
                href = a['href']
                text = a.get_text(' ', strip=True).lower()
                href_lower = href.lower()
                if any(k in href_lower or k in text for k in ['contact', 'about', 'kontakt', 'touch', 'reach']):
                    full_link = urljoin(base_url, href)
                    if full_link not in pages_to_check and len(pages_to_check) < 6:
                        pages_to_check.append(full_link)

    except Exception:
        pass

    # 2. Projít nalezené kontaktní podstránky
    for page in pages_to_check:
        if page in visited or len(emails) >= 2:
            continue
        visited.add(page)
        try:
            req = urllib.request.Request(page, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content = resp.read()
                for enc in ['utf-8', 'cp1250', 'iso-8859-1']:
                    try:
                        html = content.decode(enc)
                        break
                    except:
                        html = content.decode('utf-8', errors='ignore')

                for m in email_regex.findall(html):
                    c = clean_email(m)
                    if c: emails.add(c)
        except Exception:
            continue

    return list(emails)

if __name__ == '__main__':
    res = find_emails_from_site('http://keramika-dub.cz/')
    print('Výsledek hledání e-mailů na keramika-dub.cz:', res)
