"""Serve the single-page application shell.

The UI is a static SPA (templates/index.html + static/app.js + static/app.css)
that talks to the authenticated REST API. This view just returns the shell for
any non-API route so the app can use clean client-side navigation.
"""
from django.shortcuts import render


def spa(request):
    return render(request, "index.html")
