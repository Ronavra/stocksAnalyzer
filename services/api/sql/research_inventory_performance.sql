-- Inventory aggregates need observation clocks and kinds, never evidence payloads.
-- Covering indexes avoid walking large document/event heaps on a cold cache.
create index if not exists research_evidence_inventory_cover_idx
 on public.research_evidence_events(company_id,kind,observed_at) include(event_date);
create index if not exists research_documents_inventory_cover_idx
 on public.research_documents(company_id,observed_at) include(kind,published_at);
create index if not exists disclosures_inventory_cover_idx
 on public.company_disclosures(company_id,filing_date)
 include(form,ownership_parsed_at,ownership_status,documents_collected_at);
