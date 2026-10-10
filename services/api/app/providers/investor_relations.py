"""Explicit issuer registry; bounded downloads and allowlisted redirects."""
from html.parser import HTMLParser
from io import BytesIO
import json
from pathlib import Path
from urllib.parse import urljoin, urlparse
import re
from pypdf import PdfReader
from app.research.guidance import release_text


class Links(HTMLParser):
    def __init__(self): super().__init__(); self.links=[]; self.current=None
    def handle_starttag(self,tag,attrs):
        if tag=='a': self.current=[dict(attrs).get('href',''),'']
    def handle_data(self,text):
        if self.current is not None: self.current[1]+=text
    def handle_endtag(self,tag):
        if tag=='a' and self.current is not None: self.links.append(tuple(self.current)); self.current=None


def allowed_url(url,hosts):
    parsed=urlparse(url)
    return parsed.scheme=='https' and parsed.hostname in hosts and not parsed.username and not parsed.password and parsed.port in (None,443)


async def download(client,url,hosts):
    for _ in range(5):
        if not allowed_url(url,hosts): raise ValueError('IR URL is outside the issuer allowlist')
        async with client.stream('GET',url) as response:
            if response.is_redirect:
                url=urljoin(url,response.headers.get('location',''));continue
            response.raise_for_status();parts=[];size=0
            async for part in response.aiter_bytes():
                size+=len(part)
                if size>15_000_000: raise ValueError('IR document exceeds limit')
                parts.append(part)
            return url,b''.join(parts),response.headers.get('content-type','')
    raise ValueError('IR redirect limit reached')


def document_text(raw,content_type,url):
    if 'pdf' in content_type or url.lower().endswith('.pdf'):
        reader=PdfReader(BytesIO(raw))
        if len(reader.pages)>200: raise ValueError('IR PDF exceeds page limit')
        parts=[]
        for page in reader.pages:
            contents=page.get_contents()
            if contents is not None and len(contents.get_data())>10_000_000: raise ValueError('IR PDF page content exceeds limit')
            parts.append(page.extract_text() or '')
        text='\n'.join(parts)
        if not text.strip(): raise ValueError('IR PDF needs OCR; not parsed as empty evidence')
        from html import escape
        return '<p>'+escape(text).replace('\n','</p><p>')+'</p>'
    if 'html' not in content_type and 'text/plain' not in content_type: raise ValueError('Unsupported IR document type')
    return raw.decode('utf-8',errors='replace')


def discovered_links(url,html,hosts):
    parser=Links();parser.feed(html);rows=[]
    for href,label in parser.links:
        target=urljoin(url,href).split('#')[0]
        if not allowed_url(target,hosts): continue
        label=re.sub(r'\s+',' ',label).strip()
        kind='transcript' if re.search(r'\btranscript\b',label,re.I) else 'presentation' if re.search(r'presentation|CFO commentary|financial summary',label,re.I) else 'official_release' if re.search(r'press release|earnings release',label,re.I) else None
        if kind and not any(x['url']==target for x in rows): rows.append({'url':target,'kind':kind})
    return rows[:12]


def registry():
    return json.loads((Path(__file__).resolve().parents[2]/'config'/'investor_relations.json').read_text())
