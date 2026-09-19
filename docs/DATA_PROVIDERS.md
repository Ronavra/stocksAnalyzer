# Data providers

## Initial adapter: Financial Modeling Prep (FMP)

The first live adapter targets FMP because its current stable API exposes normalized income statements, balance sheets, cash-flow statements and analyst estimates behind one provider interface.

This is an implementation choice, not a permanent dependency. The provider abstraction lets us replace or augment FMP later.

### Environment
Set `FMP_API_KEY` only on the backend. Never expose it through a `NEXT_PUBLIC_` variable.

### Source strategy
- SEC/company filings remain the primary evidence layer for reported facts.
- FMP supplies normalized fundamentals and analyst consensus inputs.
- Market/news providers can be split out later if coverage, licensing or cost makes that preferable.
