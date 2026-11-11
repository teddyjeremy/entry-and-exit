# Vercel dashboard

Deploy this directory as a Next.js project. Configure server-only environment variables:
- PAPER_API_URL: HTTPS Cloud Run service URL
- PAPER_API_TOKEN: same value as Secret Manager secret paper-dashboard-token

The dashboard proxy keeps the API token server-side. Protect the Vercel project with password protection or team-only access before exposing portfolio data.
