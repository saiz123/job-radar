from curl_cffi import requests as rq
from pathlib import Path
urls=[
 'https://www.dol.gov/media/LCA_Disclosure_Data_FY2026_Q3.xlsx',
 'https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2025_Q4.xlsx',
 'https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2023_Q4.xlsx',
]
out=Path('data/sponsorship'); out.mkdir(exist_ok=True, parents=True)
for url in urls:
    name=url.rsplit('/',1)[-1]
    print('try',url, flush=True)
    try:
        r=rq.get(url, impersonate='chrome120', timeout=180, headers={'referer':'https://www.dol.gov/agencies/eta/foreign-labor/performance'})
        print('status', r.status_code, r.headers.get('content-type'), len(r.content), flush=True)
        if r.status_code!=200:
            continue
        p=out/name
        p.write_bytes(r.content)
        print('saved',p,p.stat().st_size)
        break
    except Exception as e:
        print('ERR',type(e).__name__,e)
