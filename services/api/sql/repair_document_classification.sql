-- Correct only classification metadata from the initial collector default.
-- Preserve source content, hashes and original publication/collection times.
with repaired as (
  update public.research_documents
  set kind='official_release'
  where source='sec' and kind='earnings_release'
    and substring(content,1,1500) !~* 'earnings release|financial results|quarterly results|full.year results'
  returning id
)
insert into public.research_collection_checks(family,source,status,checked_at,metadata)
select 'filings','document_classification_v2','success',now(),
       jsonb_build_object('classification_metadata_repaired',count(*),'content_and_timestamps_preserved',true)
from repaired;
