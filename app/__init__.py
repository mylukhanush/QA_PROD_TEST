"""
Flask application factory.
"""
import os
from flask import Flask
from db import db, migrate


def create_app(config_overrides=None):
    """Create and configure the Flask application."""
    from app.logging_config import configure_logging
    configure_logging()

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    # ── Core config ───────────────────────────────────────────────
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-secret")

    # ── Database Connection and Fallback ──────────────────────────
    db_url = os.getenv("DATABASE_URL")
    if db_url and db_url.startswith("postgresql"):
        try:
            from sqlalchemy import create_engine
            # Attempt a quick test connection
            engine = create_engine(db_url, connect_args={"connect_timeout": 3})
            connection = engine.connect()
            connection.close()
            engine.dispose()
            print("PostgreSQL database connection verified.")
        except Exception as e:
            print(f"\n[WARNING] PostgreSQL connection failed: {e}")
            print("Falling back to local SQLite database: sqlite:///qa_automation.db\n")
            db_url = "sqlite:///qa_automation.db"

    app.config["SQLALCHEMY_DATABASE_URI"] = db_url or "sqlite:///qa_automation.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SCREENSHOTS_DIR"] = os.getenv("SCREENSHOTS_DIR", "screenshots")
    app.config["REPORTS_DIR"] = os.getenv("REPORTS_DIR", "reports")
    app.config["SITE_MAP_PATH"] = os.getenv("SITE_MAP_PATH", "site-map.json")

    if config_overrides:
        app.config.update(config_overrides)

    # ── Extensions ────────────────────────────────────────────────
    db.init_app(app)
    migrations_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'db', 'migrations')
    migrate.init_app(app, db, directory=migrations_dir)

    # ── Database Initialization & Migration ───────────────────────
    with app.app_context():
        db_path = None
        if app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///"):
            db_file = app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", "")
            if not os.path.isabs(db_file):
                db_path = os.path.join(app.instance_path, db_file)
            else:
                db_path = db_file

        def do_migration():
            from flask_migrate import upgrade as flask_db_upgrade
            print("Applying database migrations programmatically...")
            flask_db_upgrade(directory=migrations_dir)
            print("Database migration completed successfully.")

        try:
            do_migration()
        except Exception as e:
            print(f"Programmatic migration failed: {e}")
            if db_path and os.path.exists(db_path):
                print(f"SQLite database might be in a corrupted or half-migrated state. Resetting {db_path}...")
                try:
                    db.session.remove()
                    db.engine.dispose()
                    os.remove(db_path)
                    print("Deleted corrupted database file. Retrying migration on clean database...")
                    do_migration()
                except Exception as ex:
                    print(f"Failed to reset database file: {ex}")
                    try:
                        print("Falling back to db.create_all()...")
                        db.create_all()
                        print("db.create_all() completed.")
                    except Exception as exc:
                        print(f"db.create_all() failed: {exc}")
            else:
                try:
                    print("Falling back to db.create_all()...")
                    db.create_all()
                    print("db.create_all() completed.")
                except Exception as ex:
                    print(f"db.create_all() failed: {ex}")

        # Seed the sites automatically if they don't exist
        try:
            from db.models import Site
            sites_data = [
                {"name": "jhs81", "base_url": os.getenv("JHS81_URL", "http://jhs81.assettl.com")},
                {"name": "jhs82", "base_url": os.getenv("JHS82_URL", "http://jhs82.assettl.com")},
                {"name": "jhs83", "base_url": os.getenv("JHS83_URL", "http://jhs83.assettl.com")},
                {"name": "jhs84", "base_url": os.getenv("JHS84_URL", "http://jhs84.assettl.com")},
            ]
            for sd in sites_data:
                existing = Site.query.filter_by(name=sd["name"]).first()
                if not existing:
                    site = Site(name=sd["name"], base_url=sd["base_url"])
                    db.session.add(site)
                    print(f"Seeded site {sd['name']} → {sd['base_url']}")
            db.session.commit()
            print("Seeded active sites successfully.")
        except Exception as e:
            print(f"Failed to seed sites: {e}")

        # Ensure duration_ms column exists in run_steps table (self-healing DDL patch)
        try:
            from sqlalchemy import text
            print("Ensuring duration_ms column exists in run_steps table...")
            db.session.execute(text("ALTER TABLE run_steps ADD COLUMN duration_ms INTEGER;"))
            db.session.commit()
            print("Successfully added duration_ms column to run_steps table.")
        except Exception:
            db.session.rollback()

        # Database schema verification logging
        try:
            from sqlalchemy import inspect
            from app.logging_config import log_event
            inspector = inspect(db.engine)
            cols = [c['name'] for c in inspector.get_columns('test_runs')]
            log_event("database_verification", test_runs_columns=cols)
            print(f"DATABASE VERIFICATION: test_runs columns are: {cols}")
        except Exception as e:
            print(f"DATABASE VERIFICATION FAILED: {e}")

    # ── Ensure directories exist ──────────────────────────────────
    os.makedirs(app.config["SCREENSHOTS_DIR"], exist_ok=True)
    os.makedirs(app.config["REPORTS_DIR"], exist_ok=True)

    # ── Register blueprints ───────────────────────────────────────
    from app.routes.crawler import crawler_bp
    from app.routes.runner import runner_bp
    from app.routes.results import results_bp
    from app.routes.history import history_bp
    from app.routes.suites import suites_bp
    from app.routes.kpi_runner import kpi_runner_bp

    app.register_blueprint(crawler_bp)
    app.register_blueprint(runner_bp)
    app.register_blueprint(results_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(suites_bp)
    app.register_blueprint(kpi_runner_bp)

    # ── Authentication Hook and Routes ───────────────────────────
    from flask import request, redirect, url_for, session, render_template, jsonify

    @app.before_request
    def check_login():
        if request.endpoint in ("login", "login_jhs", "logout", "static") or not request.endpoint:
            return
        if not session.get("jhs_username") or not session.get("jhs_password"):
            return redirect(url_for("login_jhs"))

    @app.route("/login")
    def login():
        return redirect(url_for("login_jhs"))

    @app.route("/login-jhs", methods=["GET", "POST"])
    def login_jhs():
        error = None
        otp_sent = False
        username = session.get("jhs_temp_username")
        password = session.get("jhs_temp_password")
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        
        if request.method == "POST":
            action = request.form.get("action", "send_otp")
            
            if action == "send_otp":
                username = (request.form.get("username") or "").strip()
                password = (request.form.get("password") or "").strip()
                
                if not username or not password:
                    error = "Please enter both Email and Password."
                    if is_ajax:
                        return jsonify({"success": False, "error": error})
                else:
                    pass

                    # Trigger background headless Playwright JHS thread
                    from app.jhs_session_manager import JHSSession, jhs_active_sessions
                    session_obj = JHSSession(username, password)
                    
                    # Register session active state immediately so verify_otp can access it
                    jhs_active_sessions[session_obj.id] = session_obj
                    session["jhs_temp_session_id"] = session_obj.id
                    session["jhs_temp_username"] = username
                    session["jhs_temp_password"] = password
                    
                    session_obj.start() # Spawns background worker thread!
                    
                    # Wait for Playwright background worker to reach OTP stage (timeout 25s)
                    ready = session_obj.otp_ready_event.wait(timeout=25.0)
                    
                    if ready and not session_obj.error:
                        if is_ajax:
                            return jsonify({"success": True, "otp_sent": True})
                    else:
                        error_msg = session_obj.error or "Connection to JHS portal timed out. Please try again."
                        # Clean up failed session
                        session_obj.close()
                        jhs_active_sessions.pop(session_obj.id, None)
                        session.pop("jhs_temp_session_id", None)
                        session.pop("jhs_temp_username", None)
                        session.pop("jhs_temp_password", None)
                        if is_ajax:
                            return jsonify({"success": False, "error": error_msg})
            
            elif action == "verify_otp":
                otp_code = (request.form.get("otp_code") or "").strip()
                session_id = session.get("jhs_temp_session_id")
                temp_user = session.get("jhs_temp_username")
                temp_pass = session.get("jhs_temp_password")
                
                if not otp_code:
                    error = "Please enter the OTP code."
                    otp_sent = True
                    if is_ajax:
                        return jsonify({"success": False, "error": error})
                else:
                    pass

                    from app.jhs_session_manager import jhs_active_sessions
                    session_obj = jhs_active_sessions.get(session_id)
                    
                    if not session_obj:
                        error = "Your JHS credentials verification session has expired. Please try again."
                        otp_sent = False
                        if is_ajax:
                            return jsonify({"success": False, "error": error, "expired": True})
                    else:
                        # Supply code to background loop and signal it to proceed
                        session_obj.otp_code = otp_code
                        session_obj.otp_input_event.set()
                        
                        # Wait for worker thread to submit OTP and verify success (timeout 30s)
                        finished = session_obj.login_result_event.wait(timeout=30.0)
                        
                        if finished and session_obj.success:
                            # Save validated credentials into current session context
                            session["jhs_username"] = session_obj.username
                            session["jhs_password"] = session_obj.password
                            
                            # Clean up
                            session_obj.close()
                            jhs_active_sessions.pop(session_id, None)
                            session.pop("jhs_temp_session_id", None)
                            session.pop("jhs_temp_username", None)
                            session.pop("jhs_temp_password", None)
                            
                            if is_ajax:
                                return jsonify({"success": True, "redirect": url_for("runner.dashboard")})
                            return redirect(url_for("runner.dashboard"))
                        else:
                            error = session_obj.error or "Incorrect or expired OTP code, or JHS portal request timeout."
                            otp_sent = True
                            
                            # Check if the browser background thread is still alive
                            still_alive = session_obj.is_alive
                            
                            if not still_alive:
                                # Clean up if thread died
                                session_obj.close()
                                jhs_active_sessions.pop(session_id, None)
                                session.pop("jhs_temp_session_id", None)
                            
                            if is_ajax:
                                return jsonify({
                                    "success": False, 
                                    "error": error, 
                                    "expired": not still_alive
                                })
                            

                            
        return render_template("login_jhs.html", error=error, otp_sent=otp_sent, username=username, password=password)

    @app.route("/logout")
    def logout():
        # Clear main login states
        session.pop("logged_in", None)
        session.pop("jhs_username", None)
        session.pop("jhs_password", None)
        
        # Clear temporary login states
        session_id = session.pop("jhs_temp_session_id", None)
        if session_id:
            from app.jhs_session_manager import jhs_active_sessions
            jhs_active_sessions.pop(session_id, None)
        session.pop("jhs_temp_username", None)
        session.pop("jhs_temp_password", None)
        
        return redirect(url_for("login_jhs"))

    # ── Register CLI commands ─────────────────────────────────────
    from cli.commands import register_cli
    register_cli(app)

    # ── Pre-load Site Map to Memory Cache & Gemini Cache ──────────
    try:
        from crawler.mapper import load_site_map
        from ai.cache import get_cached_site_map_content, setup_gemini_context_cache
        from ai import generator
        print("Loading site-map.json into memory folder...")
        site_map = load_site_map(app.config["SITE_MAP_PATH"])
        site_map_json = get_cached_site_map_content(site_map)
        print("Site-map successfully cached in RAM.")
        
        print("Initializing Gemini context cache...")
        gemini_cache = setup_gemini_context_cache(site_map_json)
        if gemini_cache:
            generator._gemini_cache = gemini_cache
    except Exception as e:
        print(f"Skipping site-map pre-load: {e}")

    return app
