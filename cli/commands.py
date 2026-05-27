"""
CLI commands — Click-based interface registered as Flask CLI commands.

Usage:
    flask crawl --site jhs82
    flask run-test --situation "check NRD vehicles" --sites jhs81,jhs82
    flask results --site jhs82 --last 10
    flask compare --test-id <uuid> --sites all
    flask history --label "NRD Vehicles" --site jhs82 --days 7
    flask seed-sites
"""
import sys
import os
import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

# Force UTF-8 output on Windows to avoid cp1252 encoding errors with Rich
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

console = Console(force_terminal=True)


def register_cli(app):
    """Register all CLI commands with the Flask app."""

    @app.cli.command("seed-sites")
    def seed_sites():
        """Seed the 4 target sites into the database."""
        from db import db
        from db.models import Site
        import os

        sites_data = [
            {"name": "jhs81", "base_url": os.getenv("JHS81_URL", "http://jhs81.assettl.com")},
            {"name": "jhs82", "base_url": os.getenv("JHS82_URL", "http://jhs82.assettl.com")},
            {"name": "jhs83", "base_url": os.getenv("JHS83_URL", "http://jhs83.assettl.com")},
            {"name": "jhs84", "base_url": os.getenv("JHS84_URL", "http://jhs84.assettl.com")},
        ]

        for sd in sites_data:
            existing = Site.query.filter_by(name=sd["name"]).first()
            if existing:
                console.print(f"  [dim]Skipping {sd['name']} (already exists)[/]")
                continue
            site = Site(name=sd["name"], base_url=sd["base_url"])
            db.session.add(site)
            console.print(f"  [green]✓[/] Added {sd['name']} → {sd['base_url']}")

        db.session.commit()
        console.print("[bold green]Sites seeded successfully.[/]")

    @app.cli.command("crawl")
    @click.option("--site", required=True, help="Site to crawl (jhs81, jhs82, jhs83, jhs84)")
    def crawl_site(site):
        """Crawl a site, build site-map.json, seed database."""
        from crawler.extractor import crawl_site as do_crawl

        console.print(f"\n[bold]🔍 Crawling {site}...[/]\n")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Starting...", total=None)

            def _on_progress(pct, msg):
                progress.update(task, description=f"[{pct}%] {msg}")

            try:
                result = do_crawl(site, progress_callback=_on_progress)
                progress.update(task, description="[100%] Done")
            except Exception as exc:
                console.print(f"\n[bold red]✗ Crawl failed:[/] {exc}")
                return

        console.print(f"\n[bold green]✓ Crawl complete![/]")
        console.print(f"  Pages crawled: {result.get('pages_crawled', 0)}")
        console.print(f"  Elements found: {result.get('elements_found', 0)}")
        console.print(f"  Site map saved: {result.get('site_map_path', 'site-map.json')}")

    @app.cli.command("run-test")
    @click.option("--situation", required=True, help="Plain English test description")
    @click.option("--sites", required=True, help="Comma-separated site names or 'all'")
    def run_test(situation, sites):
        """Generate a test plan via Gemini and run with Playwright."""
        from ai.generator import generate_test_plan
        from runner.executor import execute_test_plan
        from runner.parallel import execute_parallel
        from db import db
        from db.models import Site, TestCase, TestRun
        from reports.terminal import print_run_summary
        from reports.json_report import load_json_report

        # Resolve sites
        if sites.lower() == "all":
            target_sites = ["jhs81", "jhs82", "jhs83", "jhs84"]
        else:
            target_sites = [s.strip() for s in sites.split(",")]

        console.print(f"\n[bold]🤖 Generating test plan...[/]")
        console.print(f"  Situation: [cyan]{situation}[/]")
        console.print(f"  Sites: [cyan]{', '.join(target_sites)}[/]\n")

        try:
            plan = generate_test_plan(situation, target_sites)
        except Exception as exc:
            console.print(f"[bold red]✗ Generation failed:[/] {exc}")
            return

        console.print(f"[green]✓ Plan generated:[/] {plan.get('testName', 'unnamed')}")
        console.print(f"  Category: {plan.get('category', 'unknown')}")
        console.print(f"  Steps: {len(plan.get('steps', []))}")
        console.print(f"  Parallel: {plan.get('runParallel', False)}\n")

        # Create test case and runs
        tc = TestCase(
            situation_description=situation,
            user_prompt=situation,
            category=plan.get("category", "data_presence"),
            steps=plan.get("steps", []),
            test_plan=plan,
        )
        db.session.add(tc)
        db.session.flush()

        run_ids = {}
        for sname in target_sites:
            site = Site.query.filter_by(name=sname).first()
            if not site:
                console.print(f"  [yellow]⚠ Site {sname} not found in DB — skipping[/]")
                continue
            tr = TestRun(
                test_case_id=tc.id,
                site_id=site.id,
                triggered_by="cli",
                status="running",
            )
            db.session.add(tr)
            db.session.flush()
            run_ids[sname] = str(tr.id)

        db.session.commit()

        if not run_ids:
            console.print("[bold red]✗ No valid sites to run against.[/]")
            return

        console.print(f"[bold]🏃 Running tests...[/]\n")

        # Execute
        if plan.get("runParallel") and len(run_ids) > 1:
            errors = execute_parallel(plan, run_ids)
            if errors:
                for sname, err in errors.items():
                    console.print(f"  [red]✗ {sname}: {err}[/]")
        else:
            execute_test_plan(plan, run_ids)

        # Print results
        for sname, rid in run_ids.items():
            report = load_json_report(rid)
            if report:
                print_run_summary(report)
            else:
                console.print(f"  [dim]No report generated for {sname}[/]")

    @app.cli.command("results")
    @click.option("--site", default=None, help="Filter by site name")
    @click.option("--last", default=10, type=int, help="Number of recent runs to show")
    def show_results(site, last):
        """Show recent test runs in a Rich table."""
        from db.models import Site, TestRun
        from reports.terminal import print_runs_table

        query = TestRun.query.order_by(TestRun.started_at.desc())

        if site:
            site_obj = Site.query.filter_by(name=site).first()
            if site_obj:
                query = query.filter_by(site_id=site_obj.id)

        runs = query.limit(last).all()

        runs_data = [
            {
                "description": r.test_case.situation_description if r.test_case else "—",
                "site": r.site.name if r.site else "—",
                "status": r.status,
                "duration_ms": r.duration_ms,
                "started_at": r.started_at.isoformat() if r.started_at else "—",
            }
            for r in runs
        ]

        if not runs_data:
            console.print("[dim]No runs found.[/]")
            return

        print_runs_table(runs_data)

    @app.cli.command("compare")
    @click.option("--test-id", required=True, help="Test case UUID")
    @click.option("--sites", default="all", help="Comma-separated sites or 'all'")
    def compare_results(test_id, sites):
        """Show cross-site comparison for a test case."""
        from db.models import Site, TestRun, ValueCapture
        from reports.terminal import print_comparison_table

        if sites.lower() == "all":
            site_objs = Site.query.filter_by(is_active=True).all()
        else:
            site_names = [s.strip() for s in sites.split(",")]
            site_objs = Site.query.filter(Site.name.in_(site_names)).all()

        comparison = []
        for site in site_objs:
            run = (
                TestRun.query
                .filter_by(test_case_id=test_id, site_id=site.id)
                .order_by(TestRun.started_at.desc())
                .first()
            )
            if not run:
                comparison.append({"site": site.name, "status": "not_run", "captures": []})
                continue

            captures = ValueCapture.query.filter_by(run_id=run.id).all()
            comparison.append({
                "site": site.name,
                "status": run.status,
                "captures": [
                    {
                        "label": c.label,
                        "captured_value": c.captured_value,
                        "expected_value": c.expected_value,
                        "matched": c.matched,
                    }
                    for c in captures
                ],
            })

        print_comparison_table(comparison)

    @app.cli.command("history")
    @click.option("--label", required=True, help="Metric label to track")
    @click.option("--site", default=None, help="Filter by site")
    @click.option("--days", default=7, type=int, help="Number of days to look back")
    def show_history(label, site, days):
        """Show value history for a metric."""
        from datetime import datetime, timedelta, timezone
        from db.models import Site, ValueCapture
        from reports.terminal import print_history_table

        since = datetime.now(timezone.utc) - timedelta(days=days)
        query = ValueCapture.query.filter(
            ValueCapture.label == label,
            ValueCapture.captured_at >= since,
        ).order_by(ValueCapture.captured_at)

        if site:
            site_obj = Site.query.filter_by(name=site).first()
            if site_obj:
                query = query.filter_by(site_id=site_obj.id)

        captures = query.all()

        data = [
            {
                "site": c.site.name if c.site else "—",
                "value": c.captured_value,
                "captured_at": c.captured_at.isoformat() if c.captured_at else "—",
            }
            for c in captures
        ]

        if not data:
            console.print(f"[dim]No history found for '{label}' in the last {days} days.[/]")
            return

        print_history_table(label, data)
