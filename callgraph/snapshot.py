# usage: snapshot.py <tree> <snapshot out>   (entrypoints come from <tree>/.trailmark/entrypoints.toml)
import sys
from pathlib import Path
from trailmark.query.api import QueryEngine
e = QueryEngine.from_directory(sys.argv[1], language="cpp,c,rust")
Path(sys.argv[2]).write_text(e.to_snapshot())
