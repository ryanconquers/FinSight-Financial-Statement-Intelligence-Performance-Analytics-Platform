# Local and deployment setup

## Local development

Use Python 3.11+ and Node.js 22.13+ (required by the current ESLint toolchain). From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
set -a && source .env && set +a
PYTHONPATH=src uvicorn finsight.api.app:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal:

```bash
cd web
cp .env.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`; the API health endpoint is `http://localhost:8000/api/health`, and interactive API documentation is available at `/docs`. Set `NEXT_PUBLIC_FINSIGHT_API_URL` in `web/.env.local` when the API runs at a different local URL.

## GitHub Pages frontend

The frontend exports as static HTML, CSS, and JavaScript and deploys to GitHub Pages through `.github/workflows/deploy-pages.yml`. GitHub Pages hosts the UI only; the browser calls the separately deployed Render API for status, companies, metrics, and source provenance. The build embeds the public API origin. No sample metrics are included.

The repository is configured to publish with GitHub Actions. The workflow builds the app with the repository-name base path, embeds `NEXT_PUBLIC_FINSIGHT_API_URL=https://finsight-api-2zh2.onrender.com`, and deploys the `web/out` artifact on changes to `main`. The live project site is [FinSight on GitHub Pages](https://ryanconquers.github.io/FinSight-Financial-Statement-Intelligence-Performance-Analytics-Platform/).

GitHub Pages supports static hosting from a custom GitHub Actions workflow. Next.js static export creates the files in `web/out`; server features such as the FastAPI service require a separate host. See [GitHub Pages publishing sources](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site) and [Next.js static exports](https://nextjs.org/docs/app/guides/static-exports).

## API deployment

The FastAPI backend is deployed at `https://finsight-api-2zh2.onrender.com`. The Pages workflow embeds this public API origin at build time and disables static-only mode. Live browser verification confirmed that the Pages site requests `/api/status` and `/api/companies`, both return HTTP 200, and the dashboard renders the empty-data state. The Render API's `/api/health`, `/api/status`, and `/api/companies` responses and GET preflight were also verified with `Origin: https://ryanconquers.github.io`; CORS returns the exact allowed origin and `GET, OPTIONS`. These checks verify deployment connectivity and endpoint behavior, not financial statements or figures. The API currently has no company records, so company-level metrics and provenance have not been verified end to end; those routes are requested after selecting an API-returned company. Keep `FINSIGHT_CORS_ORIGINS` set to `https://ryanconquers.github.io` in Render. The public `NEXT_PUBLIC_FINSIGHT_API_URL` value is bundled into frontend JavaScript and must contain no credentials.

The client retries network errors and transient HTTP 502/503/504 responses, allowing the Render free instance time to wake after inactivity. Failed requests end in the existing retryable error state. Dashboard metrics and provenance load only when the API returns a company; the live database currently returns an empty company list.

Render web services have an ephemeral filesystem by default. The included free service stores its empty SQLite file under `/tmp`; it can be recreated after a restart or deploy. This is acceptable only while there is no onboarded financial dataset. Render persistent disks are available to paid services and preserve files only beneath their mount path. Before onboarding real data, either upgrade and mount a persistent disk (for example `/var/data`, with `FINSIGHT_DATABASE_PATH=/var/data/finsight.sqlite3`) or migrate to managed PostgreSQL. Do not rely on the included ephemeral SQLite path for durable disclosures. See [Render web services](https://render.com/docs/web-services) and [Render disks](https://render.com/docs/disks).

The static frontend is deployed on GitHub Pages, and the FastAPI backend is deployed separately on Render. No financial statements or figures have been independently verified.
