"""Memorius bookcase — browser-based 3D vault bookcase with a guiding
librarian voice.

Shipped as package data so ``pip install memorius`` works outside a
checkout. Launch path: ``memorius bookcase`` (loopback static server +
REST API). See dev-notes/GOAL-bookcase-3d-librarian.md.

Files:
  bookcase.html        page skeleton (DOM contract documented in its header)
  bookcase.css         dark/cinematic styling (orange accent, site language)
  bookcase.js          bootstrap + data flow + UI wiring (main module)
  bookcase-scene.js    Three.js 3D bookcase (rows of books, fly-to, marks)
  bookcase-librarian.js Web Speech API voice guidance (output + hold-to-talk)
"""
