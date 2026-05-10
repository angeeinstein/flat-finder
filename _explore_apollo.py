import json

with open('_immoscout24___APOLLO_STATE__.json', encoding='utf-8') as f:
    data = json.load(f)

expose_key = [k for k in data if k.startswith('Expose:')][0]
e = data[expose_key]

print('=== DESCRIPTION ===')
print(json.dumps(e['description'], ensure_ascii=False, indent=2))

print()
print('=== ALL PICTURE URLS ===')
pics = e.get('pictures', [])
print(f'Total pictures: {len(pics)}')
for i, p in enumerate(pics):
    if isinstance(p, dict):
        print(f'  [{i+1}] keys={list(p.keys())}')
        for k, v in p.items():
            print(f'       {k}: {repr(v)[:200]}')
    elif isinstance(p, str):
        print(f'  [{i+1}] {p}')

print()
print('=== PRICE INFORMATION ===')
print(json.dumps(e['priceInformation'], ensure_ascii=False, indent=2))

print()
print('=== COSTS ===')
print(json.dumps(e['costs'], ensure_ascii=False, indent=2))

print()
print('=== AREA ===')
print(json.dumps(e['area'], ensure_ascii=False, indent=2))

print()
print('=== LOCALIZATION ===')
print(json.dumps(e['localization'], ensure_ascii=False, indent=2))

print()
print('=== CHARACTERISTICS ===')
for c in e['characteristics']:
    print(f'  {json.dumps(c, ensure_ascii=False)}')

print()
print('=== CONDITION ===')
print(json.dumps(e['condition'], ensure_ascii=False, indent=2))

print()
print('=== OBJECT ===')
print(json.dumps(e['object'], ensure_ascii=False, indent=2))

print()
print('=== FITTING ===')
print(json.dumps(e['fitting'], ensure_ascii=False, indent=2))

print()
print('=== KEYFACTS ===')
print(json.dumps(e['keyfacts'], ensure_ascii=False, indent=2))

print()
print('=== CONTACT ===')
print(json.dumps(e['contact'], ensure_ascii=False, indent=2))

print()
print('=== ATTACHMENTS ===')
atts = e.get('attachments', [])
print(f'Total attachments: {len(atts)}')
for i, a in enumerate(atts):
    print(f'  [{i+1}] {json.dumps(a, ensure_ascii=False)[:200]}')
