"""Normalize reviewable source observations without inferring absent facts."""
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import math
import re
import xml.etree.ElementTree as ET
from .guidance import release_text


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def document(company_id, url, html, observed_at, published_at=None, accession=None, kind=None):
    text = release_text(html)
    # A passing reference to a call is not a transcript.
    if kind is None:
        lead = text[:1500]
        kind = 'transcript' if re.search(r'\btranscript\b', lead, re.I) and re.search(r'conference call|earnings call', lead, re.I) else 'presentation' if re.search(r'\b(?:investor|earnings) presentation\b', lead, re.I) else 'earnings_release'
    if not text.strip():
        raise ValueError('Document has no visible content')
    if published_at and datetime.fromisoformat(published_at.replace('Z', '+00:00')) > datetime.fromisoformat(observed_at.replace('Z', '+00:00')):
        raise ValueError('Publication is in the future')
    title_match=re.search(r'<title[^>]*>(.*?)</title>',html,re.I|re.S)
    title=release_text(title_match.group(1)) if title_match else text.splitlines()[0]
    return {'company_id': company_id, 'kind': kind, 'source': 'sec' if accession else 'company_ir',
            'source_url': url, 'source_record_id': accession or url, 'published_at': published_at,
            'observed_at': observed_at, 'title': title[:200],
            'content': text[:200_000], 'content_hash': sha256(text.encode()).hexdigest(), 'truncated': len(text) > 200_000}


def evidence_event(company_id, kind, source, record_id, url, payload, observed_at, event_date=None, published_at=None):
    return {'company_id': company_id, 'kind': kind, 'source': source, 'source_record_id': str(record_id),
            'source_url': url, 'payload': payload, 'fingerprint': fingerprint(payload),
            'observed_at': observed_at, 'published_at': published_at, 'event_date': event_date}


def insider_transactions(xml, company, event, observed_at):
    root = ET.fromstring(xml)
    # SEC ownership XML is commonly unnamespaced; support namespace-qualified files too.
    for node in root.iter(): node.tag = node.tag.split('}')[-1]
    issuer = root.findtext('issuer/issuerCik')
    if not issuer or issuer.lstrip('0') != str(company['cik']).lstrip('0'):
        raise ValueError('Ownership filing issuer identity mismatch')
    owners = [{'name': x.findtext('reportingOwnerId/rptOwnerName'), 'cik': x.findtext('reportingOwnerId/rptOwnerCik'),
               'relationship': {n.tag: n.text for n in x.findall('reportingOwnerRelationship/*')}} for x in root.findall('reportingOwner')]
    rows = []
    for i, txn in enumerate(root.findall('.//nonDerivativeTransaction') + root.findall('.//derivativeTransaction')):
        value = lambda p: txn.findtext(p + '/value')
        shares = number(value('transactionAmounts/transactionShares'))
        price = number(value('transactionAmounts/transactionPricePerShare'))
        code = txn.findtext('transactionCoding/transactionCode')
        when = value('transactionDate')
        if when:
            date.fromisoformat(when)
            if when > observed_at[:10]: raise ValueError('Ownership transaction is in the future')
        payload = {'security': value('securityTitle'), 'owners': owners, 'transaction_code': code,
                   'direction': value('transactionAmounts/transactionAcquiredDisposedCode'),
                   'shares': shares, 'price_per_share': price, 'reported_value': shares * price if shares is not None and price is not None else None,
                   'post_transaction_shares': number(value('postTransactionAmounts/sharesOwnedFollowingTransaction')),
                   'derivative': txn.tag == 'derivativeTransaction', 'purchase_or_private_purchase': code == 'P',
                   'planned_10b5_1': root.findtext('aff10b5One'),
                   'footnotes': {x.attrib.get('id'): ''.join(x.itertext()) for x in root.findall('footnotes/footnote')},
                   'amendment': event['form'].endswith('/A')}
        # Joint reporting persons describe one transaction, not one transaction per person.
        rows.append(evidence_event(company['id'], 'insider_transaction', 'sec_form4', f"{event['accession_number']}:{i}", event['source_url'], payload, observed_at, when, event['published_at']))
    return rows


def corporate_actions(company_id, data, kind, observed_at):
    field = 'dividends' if kind == 'dividend' else 'splits'
    if not isinstance(data, dict) or not isinstance(data.get(field), list):
        raise ValueError('Corporate action response has no expected event array')
    rows = []
    for item in data[field]:
        when = item.get('ex_date') if kind == 'dividend' else item.get('date')
        if not when: continue
        date.fromisoformat(when)
        if kind == 'dividend':
            amount = number(item.get('amount'))
            if amount is None or amount < 0: continue
            payload = {'amount': amount, 'currency': (data.get('meta') or {}).get('currency'), 'ex_date': when}
        else:
            ratio = number(item.get('ratio'))
            if ratio is None or ratio <= 0: continue
            payload = {'ratio': ratio, 'description': item.get('description'), 'date': when}
        # Ex-date is not publication date; historical events first observed now.
        rows.append(evidence_event(company_id, kind, 'twelvedata', when, 'https://twelvedata.com/docs', payload, observed_at, when))
    return rows
