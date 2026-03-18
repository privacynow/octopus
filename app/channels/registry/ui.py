"""Registry-channel UI rendering helpers."""

from __future__ import annotations

import html


def render_login_html(heading: str, *, error: str = "") -> str:
    error_html = (
        f'<div class="error">{html.escape(error)}</div>'
        if error else
        ""
    )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{html.escape(heading)} — Login</title>
    <style>
      :root {{
        color-scheme: dark;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                     "Helvetica Neue", Arial, sans-serif;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        background:
          radial-gradient(circle at top right, rgba(15, 118, 110, 0.22), transparent 30%),
          linear-gradient(180deg, #0f172a 0%, #111827 100%);
        color: #e5e7eb;
      }}
      .card {{
        width: min(320px, calc(100vw - 2rem));
        padding: 1.5rem;
        border-radius: 1rem;
        background: #1e293b;
        border: 1px solid rgba(148, 163, 184, 0.18);
        box-shadow: 0 18px 48px rgba(0, 0, 0, 0.32);
      }}
      h1 {{
        margin: 0 0 0.4rem;
        font-size: 1.2rem;
      }}
      p {{
        margin: 0 0 1rem;
        color: #cbd5e1;
        font-size: 0.92rem;
      }}
      label {{
        display: block;
        margin-bottom: 0.45rem;
        color: #cbd5e1;
        font-size: 0.92rem;
      }}
      input {{
        width: 100%;
        padding: 0.8rem 0.9rem;
        border-radius: 0.8rem;
        border: 1px solid rgba(148, 163, 184, 0.25);
        background: #0f172a;
        color: #f8fafc;
        margin-bottom: 0.9rem;
      }}
      button {{
        width: 100%;
        border: 0;
        border-radius: 0.8rem;
        padding: 0.85rem 1rem;
        background: #0f766e;
        color: #f8fafc;
        font: inherit;
        cursor: pointer;
      }}
      .error {{
        margin-bottom: 0.9rem;
        color: #fca5a5;
        font-size: 0.9rem;
      }}
    </style>
  </head>
  <body>
    <form class="card" method="post" action="/ui/login">
      <h1>{html.escape(heading)}</h1>
      <p>Enter the Registry UI password to continue.</p>
      {error_html}
      <label for="password">Password</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required />
      <button type="submit">Log in</button>
    </form>
  </body>
</html>"""
