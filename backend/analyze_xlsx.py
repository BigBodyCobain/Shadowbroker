import zipfile
import xml.etree.ElementTree as ET
import re
import csv
import os

xlsx_path = r"f:\Codebase\Oracle\live-risk-dashboard\TheAirTraffic Database.xlsx"
output_path = r"f:\Codebase\Oracle\live-risk-dashboard\backend\xlsx_analysis.txt"

def parse_xlsx_sheet(z, shared_strings, sheet_num):
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    sheet_file = f'xl/worksheets/sheet{sheet_num}.xml'
    if sheet_file not in z.namelist():
        return []
    ws_xml = z.read(sheet_file)
    ws_root = ET.fromstring(ws_xml)
    rows = []
    for row in ws_root.findall('.//s:sheetData/s:row', ns):
        cells = {}
        for cell in row.findall('s:c', ns):
            cell_ref = cell.get('r', '')
            cell_type = cell.get('t', '')
            val_elem = cell.find('s:v', ns)
            val = val_elem.text if val_elem is not None else ''
            if cell_type == 's' and val:
                val = shared_strings[int(val)]
            col = re.match(r'([A-Z]+)', cell_ref).group(1) if re.match(r'([A-Z]+)', cell_ref) else ''
            cells[col] = val
        rows.append(cells)
    return rows

with open(output_path, 'w', encoding='utf-8') as out:
    with zipfile.ZipFile(xlsx_path, 'r') as z:
        shared_strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            ss_xml = z.read('xl/sharedStrings.xml')
            root = ET.fromstring(ss_xml)
            ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            for si in root.findall('.//s:si', ns):
                texts = si.findall('.//s:t', ns)
                val = ''.join(t.text or '' for t in texts)
                shared_strings.append(val)
        
        all_entries = []
        for sheet_idx in range(1, 5):
            rows = parse_xlsx_sheet(z, shared_strings, sheet_idx)
            if not rows:
                continue
            
            out.write(f"\n=== SHEET {sheet_idx}: {len(rows)} rows ===\n")
            # Print first 5 rows
            for i in range(min(5, len(rows))):
                for col in sorted(rows[i].keys(), key=lambda x: (len(x), x)):
                    val = rows[i][col]
                    if val:
                        out.write(f"  Row{i} {col}: '{val[:80]}'\n")
                out.write("\n")
            
            for r in rows[1:]:
                for col, val in r.items():
                    val = str(val).strip()
                    n_regs = re.findall(r'N\d{1,5}[A-Z]{0,2}', val)
                    owner = r.get('B', r.get('A', '')).strip()
                    aircraft_type = r.get('C', r.get('D', '')).strip()
                    for reg in n_regs:
                        all_entries.append({
                            'registration': reg.upper(),
                            'owner': owner,
                            'type': aircraft_type,
                            'sheet': sheet_idx
                        })
    
    unique_regs = set(e['registration'] for e in all_entries)
    out.write(f"\nTOTAL ENTRIES: {len(all_entries)}\n")
    out.write(f"UNIQUE REGISTRATIONS: {len(unique_regs)}\n")
    
    csv_path = r"f:\Codebase\Oracle\live-risk-dashboard\PLANEALERTLIST\plane-alert-db-main\plane-alert-db.csv"
    existing = {}
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            icao = row.get('$ICAO', '').strip().upper()
            reg = row.get('$Registration', '').strip().upper()
            if reg:
                existing[reg] = {
                    'icao': icao,
                    'category': row.get('Category', ''),
                    'operator': row.get('$Operator', ''),
                }
    
    already_in = unique_regs & set(existing.keys())
    missing = unique_regs - set(existing.keys())
    out.write(f"\nplane-alert-db: {len(existing)} registrations\n")
    out.write(f"Already covered: {len(already_in)}\n")
    out.write(f"MISSING: {len(missing)}\n")
    
    out.write(f"\n--- ALREADY TRACKED ---\n")
    seen = set()
    for e in all_entries:
        if e['registration'] in already_in and e['registration'] not in seen:
            info = existing[e['registration']]
            out.write(f"  {e['owner'][:40]:40s} {e['registration']:10s} DB_CAT: {info['category'][:25]:25s} DB_OP: {info['operator'][:40]}\n")
            seen.add(e['registration'])
    
    out.write(f"\n--- MISSING (NEED TO ADD) ---\n")
    seen = set()
    for e in all_entries:
        if e['registration'] in missing and e['registration'] not in seen:
            out.write(f"  {e['owner'][:40]:40s} {e['registration']:10s} TYPE: {e['type'][:30]}\n")
            seen.add(e['registration'])

print(f"Analysis written to {output_path}")
