from pathlib import Path

path = Path("scripts/_workbench2_linked_strategy_patch.py")
text = path.read_text(encoding="utf-8")
old = '''    '<Link to={`/research-graph${workbenchContextSearch(context)}`}><GitBranch size={13} /> Research Graph</Link>',
    '<Link to={`/research-graph${workbenchContextSearch(context)}`}><GitBranch size={13} /> Research Graph</Link><Link to={`/strategy${workbenchContextSearch(context)}`}>Strategy / terminal</Link>',
'''
new = '''    '<Link to={`/research-graph${workbenchContextSearch(context)}`}>Open Research Graph</Link>',
    '<Link to={`/research-graph${workbenchContextSearch(context)}`}>Open Research Graph</Link><Link to={`/strategy${workbenchContextSearch(context)}`}>Strategy / terminal</Link>',
'''
if old not in text:
    raise SystemExit("experiments patch anchor source not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
