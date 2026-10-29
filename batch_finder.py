"""
Batch finder for 20 oldest website contacts in US local businesses.
Runs targeted queries across Illinois metros until at least 20 verified email leads with outdated code are acquired.
Syncs immediately to Google Sheets.
"""

import sys
import os
import time
import sqlite3

sys.path.insert(0, '/home/q/Research/us-leads-engine')
from lead_engine import (
    init_db, search_yahoo_outdated, audit_website_code,
    find_emails_from_site, insert_lead, is_already_in_db,
    sync_to_google_sheets, export_to_excel, export_csv_for_gsheet,
    DEFAULT_GSHEET_ID, DB_PATH
)

TARGET_HOT_LEADS = 20

SEARCH_TARGETS = [
    ('Rockford, IL', 'roofing contractor'),
    ('Peoria, IL', 'plumbing heating'),
    ('Springfield, IL', 'hvac repair'),
    ('Naperville, IL', 'tree service trimming'),
    ('Aurora, IL', 'electrician commercial residential'),
    ('Joliet, IL', 'general contractor construction'),
    ('Elgin, IL', 'roofing siding'),
    ('Waukegan, IL', 'plumber plumbing'),
    ('Cicero, IL', 'heating air conditioning'),
    ('Arlington Heights, IL', 'painting contractor'),
    ('Evanston, IL', 'auto repair body shop'),
    ('Schaumburg, IL', 'flooring tile contractor'),
    ('Bolingbrook, IL', 'roofing repair'),
    ('Palatine, IL', 'tree removal service'),
    ('Skokie, IL', 'masonry contractor chimney'),
    ('Champaign, IL', 'plumbing contractor'),
    ('Decatur, IL', 'roofing contractor'),
    ('Bloomington, IL', 'hvac contractor'),
]

def main():
    conn = init_db()
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM leads WHERE outdated_score >= 15 AND email != ''")
    current_hot = c.fetchone()[0]
    print(f"🚀 Zahajuji sběr nejstarších webů. Aktuální stav: {current_hot}/{TARGET_HOT_LEADS}")

    for city, niche in SEARCH_TARGETS:
        if current_hot >= TARGET_HOT_LEADS:
            break

        print(f"\n==================================================")
        print(f"🎯 Sken: {niche.upper()} v {city.upper()} (aktuálně {current_hot}/{TARGET_HOT_LEADS})")
        print(f"==================================================")

        raw_leads = []
        for attempt in range(2):
            try:
                raw_leads = search_yahoo_outdated(city, niche, max_pages=2)
                break
            except Exception as e:
                print(f"  ⚠ Network retry ({attempt+1}/2): {e}")
                time.sleep(2)

        print(f"  Získáno {len(raw_leads)} domén k prověření...")

        for biz in raw_leads:
            dom = biz['domain']
            url = biz['url']
            name = biz['business_name']

            if is_already_in_db(conn, dom):
                continue

            # 1. Rychlý audit kódu
            audit = audit_website_code(url)
            score = audit['outdated_score']
            flaws = audit['technical_flaws']
            phone = audit.pop('phone', '')

            # Bereme staré a stárnoucí weby (skóre >= 15)
            if score < 15:
                continue

            print(f"\n  🔍 Prověřuji starý web ({score}/100): {name} ({dom})")
            print(f"     Vady: {flaws}")

            # 2. Hledání emailu (BEZ EMAILU NEBEREM)
            emails = find_emails_from_site(url)
            email = emails[0] if emails else ''

            if not email:
                print(f"     ❌ Nemá email -> přeskočeno")
                continue

            print(f"     ✅ NALEZEN EMAIL: {email}")

            lead_data = {
                'business_name': name,
                'niche': niche,
                'website': url,
                'email': email,
                'phone': phone,
                'city': city.split(',')[0].strip(),
                'state': 'IL',
                'scan_city': city,
                'scan_niche': niche,
                'source': 'batch_old_finder',
                'status': 'HOT_LEAD',
                **audit,
            }

            if insert_lead(conn, lead_data):
                current_hot += 1
                print(f"     🔥 Hot Lead #{current_hot}/{TARGET_HOT_LEADS} zapsán do DB!")

            if current_hot >= TARGET_HOT_LEADS:
                print(f"\n🎉 DOSAŽENO CÍLE {TARGET_HOT_LEADS} HOT LEADŮ!")
                break

            time.sleep(0.3)

    # Export a Google Sheets sync
    print(f"\n📊 Celkem uloženo {current_hot} starých webů s emailem.")
    export_to_excel(conn)
    export_csv_for_gsheet(conn)
    
    # Retry Google Sheets sync if network hiccups
    for attempt in range(3):
        try:
            if sync_to_google_sheets(conn, DEFAULT_GSHEET_ID):
                break
        except Exception as e:
            print(f"  ⚠ Google Sheets sync retry ({attempt+1}/3): {e}")
            time.sleep(2)
            
    conn.close()

if __name__ == '__main__':
    main()
