"""Direction layer (outside the core).

Tools for the director / orchestrator / worker workflow: the song dossier
(``dossier``) and the experience store ``kb/`` (``kb``). This package reads
the core and the project files; the core never imports this package and never
reads ``kb/`` (the core works the same with an empty ``kb/``).
"""

from __future__ import annotations
