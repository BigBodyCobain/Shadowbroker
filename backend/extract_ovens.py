import re
import json

try:
    with open('liveua_test.html', 'r', encoding='utf-8') as f:
        html = f.read()
        
    m = re.search(r"var\s+ovens\s*=\s*(.*?);(?!function)", html, re.DOTALL)
    if m:
        json_str = m.group(1)
        # Handle if it is a string containing base64
        if json_str.startswith("'") or json_str.startswith('"'):
            json_str = json_str.strip('"\'')
            import base64
            import urllib.parse
            json_str = base64.b64decode(urllib.parse.unquote(json_str)).decode('utf-8')
            
        data = json.loads(json_str)
        with open('out_liveua.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print(f"Successfully extracted {len(data)} ovens items.")
    else:
        print("var ovens not found.")
except Exception as e:
    print("Error:", e)
