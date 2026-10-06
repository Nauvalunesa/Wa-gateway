"""Python equivalent of relayMessage for an HTML AI Rich payload.

Preview: .venv312/bin/python examples/send_html.py --html frontend/src/rich-examples/sound.html
Send: add --send --to 628... --phone DEVICE and set UTUSAN_API_KEY.
"""
import argparse
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser()
parser.add_argument('--html', required=True)
parser.add_argument('--to', default='preview')
parser.add_argument('--phone')
parser.add_argument('--url', default='https://utusan.chat')
parser.add_argument('--send', action='store_true')
args = parser.parse_args()
payload = {'to': args.to, 'phone': args.phone, 'title': 'HTML interactif',
           'blocks': [{'type': 'html', 'html': Path(args.html).read_text(encoding='utf-8'),
                       'text': 'HTML interactif', 'trusted_sources': []}]}
if not args.send:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
else:
    if args.to == 'preview' or not args.phone:
        parser.error('--send requires --to and --phone')
    key = os.environ['UTUSAN_API_KEY']
    request = Request(args.url.rstrip('/') + '/api/send-airich',
                      data=json.dumps(payload).encode(),
                      headers={'Content-Type': 'application/json', 'X-API-Key': key})
    with urlopen(request, timeout=60) as response:
        print(response.read().decode())
