"""
console_web — the interactive query interface for Project Console.

A thin web layer over the existing domain DAOs / services. It runs the same
named queries a user would otherwise get from the dashboard, but interactively:
pick a query, pick projects, see results in the browser, and pull an Excel or
PDF export of exactly what's on screen.

The layer is deliberately thin: `queries` composes the DAOs into generic
QueryResult tables, `exporters` turns any QueryResult into xlsx/pdf, and `app`
serves them. Nothing here holds business rules the domain layer doesn't already
own — swapping the store or adding an entity changes the domain, not this.
"""
