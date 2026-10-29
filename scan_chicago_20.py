#!/usr/bin/env python3
"""
Chicago Multi-Trade Lead Scanner
Fetches at least 20 verified leads with email across multiple trades in Chicago, IL.
Audits outdated web technical indicators, saves to SQLite, syncs to Google Sheets.
"""

import os
import sys
import time
import sqlite3

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from lead_engine import (
    init_db, is_already_in_db, search_yahoo_outdated,
    audit_website_code, find_emails_from_site, insert_lead,
    export_to_excel, export_csv_for_gsheet, sync_to_google_sheets,
    DB_PATH, DEFAULT_GSHEET_ID
)

TRADES = [
    'plumber',
    'electrician',
    'painter',
    'carpentry',
    'masonry',
    'hardwood flooring',
    'hvac contractor',
    'landscaping',
    'locksmith',
    'remodeling contractor'
]

def get_current_chicago_leads(conn):
    c = conn.cursor()
    c.execute('''
        SELECT id, business_name, niche, email, phone, website,
               outdated_score, technical_flaws, website_age_indicator
        FROM leads
        WHERE email != '' AND email IS NOT NULL
          AND (scan_city LIKE '%Chicago%' OR city LIKE '%Chicago%')
        ORDER BY outdated_score DESC
    ''')
    return c.fetchall()

def run_chicago_scan(target_count=20):
    conn = init_db()
    current_leads = get_current_chicago_leads(conn)
    print(f"Current Chicago leads with email: {len(current_leads)}")

    for trade in TRADES:
        current_leads = get_current_chicago_leads(conn)
        if len(current_leads) >= target_count:
            print(f"Reached target {target_count} Chicago leads! ({len(current_leads)} total)")
            break

        print(f"\n==========================================")
        print(f"Scanning trade: {trade.upper()} in Chicago, IL")
        print(f"==========================================")

        domains_found = search_yahoo_outdated('Chicago, IL', trade, max_pages=2)
        print(f"Candidate sites found: {len(domains_found)}")

        for biz in domains_found:
            current_leads = get_current_chicago_leads(conn)
            if len(current_leads) >= target_count:
                break

            dom = biz['domain']
            if is_already_in_db(conn, dom):
                continue

            url = biz['url']
            name = biz['business_name']
            print(f"  [+] Auditing: {name} ({dom})")

            audit = audit_website_code(url, timeout=7)
            score = audit['outdated_score']
            flaws = audit['technical_flaws']
            phone = audit.pop('phone', '')

            # Email check
            emails = find_emails_from_site(url, timeout=7)
            email = emails[0] if emails else ''
            if not email:
                print(f"      (-) Bez emailu -> přeskočeno")
                continue

            print(f"      (V) Email: {email} | Skóre: {score} | Flaws: {flaws[:60] if flaws else 'None'}")

            status = 'HOT_LEAD' if score >= 25 else 'MODERN_WITH_EMAIL'
            record = {
                'business_name': name,
                'niche': trade,
                'website': url,
                'domain': dom,
                'city': 'Chicago',
                'state': 'IL',
                'scan_city': 'Chicago, IL',
                'scan_niche': trade,
                'email': email,
                'phone': phone,
                'status': status,
                'source': 'yahoo_search',
                **audit,
            }

            if insert_lead(conn, record):
                print(f"      >>> Uloženo do DB!")

            time.sleep(0.3)

    final_leads = get_current_chicago_leads(conn)
    print(f"\n==========================================")
    print(f"SCAN DOKONČEN. Chicago leadů s emailem: {len(final_leads)}")
    print(f"==========================================")

    # Sync and exports
    export_to_excel(conn)
    export_csv_for_gsheet(conn)
    try:
        sync_to_google_sheets(conn, DEFAULT_GSHEET_ID)
    except Exception as e:
        print(f"Google Sheets sync warning: {e}")

    conn.close()
    return final_leads

if __name__ == '__main__':
    run_chicago_scan(target_count=20)
