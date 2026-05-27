"""
SQLAlchemy ORM models for the QA Automation system.

Tables
------
- sites              – the 4 target sites (jhs81-84)
- site_elements      – shared CSS selector map (no site_id)
- test_cases         – universal test definitions (no site_id)
- test_runs          – individual execution records per site
- run_steps          – ordered steps within a test run
- value_captures     – values captured during runs for comparison
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text, JSON,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import relationship

from db import db


def _utcnow():
    return datetime.now(timezone.utc)


def _uuid():
    return str(uuid.uuid4())


def safe_duration_ms(started_at, finished_at):
    if not started_at or not finished_at:
        return 0
    # Convert both to UTC if they have tzinfo, otherwise assume they are naive UTC
    s = started_at.astimezone(timezone.utc) if started_at.tzinfo else started_at.replace(tzinfo=timezone.utc)
    f = finished_at.astimezone(timezone.utc) if finished_at.tzinfo else finished_at.replace(tzinfo=timezone.utc)
    s_naive = s.replace(tzinfo=None)
    f_naive = f.replace(tzinfo=None)
    return int((f_naive - s_naive).total_seconds() * 1000)


# ═══════════════════════════════════════════════════════════════════
# sites
# ═══════════════════════════════════════════════════════════════════
class Site(db.Model):
    __tablename__ = "sites"

    id         = Column(PGUUID(as_uuid=True).with_variant(String(36), "sqlite"),
                         primary_key=True, default=_uuid)
    name       = Column(String(20), unique=True, nullable=False)      # jhs81..84
    base_url   = Column(String(255), nullable=False)
    is_active  = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # relationships
    test_runs      = relationship("TestRun", back_populates="site", lazy="dynamic")
    value_captures = relationship("ValueCapture", back_populates="site", lazy="dynamic")

    def __repr__(self):
        return f"<Site {self.name}>"


# ═══════════════════════════════════════════════════════════════════
# site_elements  (shared selector map — NO site_id)
# ═══════════════════════════════════════════════════════════════════
class SiteElement(db.Model):
    __tablename__ = "site_elements"

    id             = Column(PGUUID(as_uuid=True).with_variant(String(36), "sqlite"),
                         primary_key=True, default=_uuid)
    page           = Column(String(100), nullable=False)               # dashboard, reports, login
    section        = Column(String(100), nullable=False)               # metric cards, table, nav
    label          = Column(String(255), nullable=False)               # "NRD Vehicles"
    selector       = Column(String(500), nullable=False)               # CSS selector
    element_type   = Column(String(50), nullable=False)                # metric_card, table_row, …
    is_dynamic     = Column(Boolean, default=False, nullable=False)
    value_sample   = Column(String(500), nullable=True)
    last_crawled_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<SiteElement {self.page}/{self.label}>"


# ═══════════════════════════════════════════════════════════════════
# test_cases  (universal — NO site_id)
# ═══════════════════════════════════════════════════════════════════
class TestCase(db.Model):
    __tablename__ = "test_cases"

    id                    = Column(PGUUID(as_uuid=True).with_variant(String(36), "sqlite"),
                                 primary_key=True, default=_uuid)
    name                  = Column(String(255), nullable=True)         # Human-readable name
    situation_description = Column(Text, nullable=False)
    user_prompt           = Column(Text, nullable=True)
    category              = Column(String(50), nullable=False)         # value_comparison, auth_validation, …
    steps                 = Column(JSON().with_variant(JSONB, "postgresql"),
                                  nullable=False, default=list)
    test_plan             = Column(JSON().with_variant(JSONB, "postgresql"),
                                  nullable=True)
    created_at            = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    last_run_at           = Column(DateTime(timezone=True), nullable=True)

    # relationships
    test_runs = relationship("TestRun", back_populates="test_case", lazy="dynamic")
    suites    = relationship("TestSuite", secondary="suite_test_cases", back_populates="test_cases")

    def __repr__(self):
        return f"<TestCase {self.name or self.category}: {self.situation_description[:40]}>"


# ═══════════════════════════════════════════════════════════════════
# TestSuite & Association
# ═══════════════════════════════════════════════════════════════════
class SuiteTestCase(db.Model):
    __tablename__ = "suite_test_cases"
    suite_id     = Column(PGUUID(as_uuid=True).with_variant(String(36), "sqlite"),
                          ForeignKey("test_suites.id"), primary_key=True)
    test_case_id = Column(PGUUID(as_uuid=True).with_variant(String(36), "sqlite"),
                          ForeignKey("test_cases.id"), primary_key=True)


class TestSuite(db.Model):
    __tablename__ = "test_suites"

    id          = Column(PGUUID(as_uuid=True).with_variant(String(36), "sqlite"),
                        primary_key=True, default=_uuid)
    name        = Column(String(255), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    created_at  = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # relationships
    test_cases = relationship("TestCase", secondary="suite_test_cases", back_populates="suites")
    suite_runs = relationship("SuiteRun", back_populates="suite", lazy="dynamic")

    def __repr__(self):
        return f"<TestSuite {self.name}>"


class SuiteRun(db.Model):
    __tablename__ = "suite_runs"

    id          = Column(PGUUID(as_uuid=True).with_variant(String(36), "sqlite"),
                        primary_key=True, default=_uuid)
    suite_id    = Column(PGUUID(as_uuid=True).with_variant(String(36), "sqlite"),
                        ForeignKey("test_suites.id"), nullable=False)
    started_at  = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    status      = Column(String(20), nullable=False, default="queued")  # queued, running, pass, fail, error, partial, cancel_requested, cancelled
    duration_ms = Column(Integer, nullable=True)

    # relationships
    suite     = relationship("TestSuite", back_populates="suite_runs")
    test_runs = relationship("TestRun", back_populates="suite_run", lazy="dynamic")

    def __repr__(self):
        return f"<SuiteRun {self.status} for {self.suite_id}>"



# ═══════════════════════════════════════════════════════════════════
# test_runs
# ═══════════════════════════════════════════════════════════════════
class TestRun(db.Model):
    __tablename__ = "test_runs"

    id           = Column(PGUUID(as_uuid=True).with_variant(String(36), "sqlite"),
                         primary_key=True, default=_uuid)
    test_case_id = Column(PGUUID(as_uuid=True).with_variant(String(36), "sqlite"),
                         ForeignKey("test_cases.id"), nullable=False)
    site_id      = Column(PGUUID(as_uuid=True).with_variant(String(36), "sqlite"),
                         ForeignKey("sites.id"), nullable=False)
    suite_run_id = Column(PGUUID(as_uuid=True).with_variant(String(36), "sqlite"),
                         ForeignKey("suite_runs.id"), nullable=True)
    triggered_by = Column(String(10), nullable=False, default="web")   # cli | web
    started_at   = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    finished_at  = Column(DateTime(timezone=True), nullable=True)
    status       = Column(String(20), nullable=False, default="queued")  # queued, running, pass, fail, error, cancelled
    duration_ms  = Column(Integer, nullable=True)
    report_path  = Column(String(500), nullable=True)

    # relationships
    test_case      = relationship("TestCase", back_populates="test_runs")
    site           = relationship("Site", back_populates="test_runs")
    suite_run      = relationship("SuiteRun", back_populates="test_runs")
    steps          = relationship("RunStep", back_populates="run", lazy="dynamic",
                                  order_by="RunStep.step_order")
    value_captures = relationship("ValueCapture", back_populates="run", lazy="dynamic")


    def __repr__(self):
        return f"<TestRun {self.status} on {self.site_id}>"


# ═══════════════════════════════════════════════════════════════════
# run_steps
# ═══════════════════════════════════════════════════════════════════
class RunStep(db.Model):
    __tablename__ = "run_steps"

    id              = Column(PGUUID(as_uuid=True).with_variant(String(36), "sqlite"),
                         primary_key=True, default=_uuid)
    run_id          = Column(PGUUID(as_uuid=True).with_variant(String(36), "sqlite"),
                         ForeignKey("test_runs.id"), nullable=False)
    step_order      = Column(Integer, nullable=False)
    action          = Column(String(50), nullable=False)
    description     = Column(Text, nullable=False)
    status          = Column(String(20), nullable=False, default="running")  # pass, fail, error, skipped
    error_message   = Column(Text, nullable=True)
    screenshot_path = Column(String(500), nullable=True)
    executed_at     = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    duration_ms     = Column(Integer, nullable=True)

    # relationships
    run = relationship("TestRun", back_populates="steps")

    def __repr__(self):
        return f"<RunStep #{self.step_order} {self.action} → {self.status}>"


# ═══════════════════════════════════════════════════════════════════
# value_captures
# ═══════════════════════════════════════════════════════════════════
class ValueCapture(db.Model):
    __tablename__ = "value_captures"

    id             = Column(PGUUID(as_uuid=True).with_variant(String(36), "sqlite"),
                         primary_key=True, default=_uuid)
    run_id         = Column(PGUUID(as_uuid=True).with_variant(String(36), "sqlite"),
                         ForeignKey("test_runs.id"), nullable=False)
    site_id        = Column(PGUUID(as_uuid=True).with_variant(String(36), "sqlite"),
                         ForeignKey("sites.id"), nullable=False)
    label          = Column(String(255), nullable=False)
    page           = Column(String(100), nullable=False)
    selector       = Column(String(500), nullable=False)
    captured_value = Column(String(500), nullable=False)
    expected_value = Column(String(500), nullable=True)
    matched        = Column(Boolean, nullable=True)
    captured_at    = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # relationships
    run  = relationship("TestRun", back_populates="value_captures")
    site = relationship("Site", back_populates="value_captures")

    def __repr__(self):
        return f"<ValueCapture {self.label}={self.captured_value}>"


# ═══════════════════════════════════════════════════════════════════
# kpi_download_history
# ═══════════════════════════════════════════════════════════════════
class KpiDownloadHistory(db.Model):
    __tablename__ = "kpi_download_history"

    id            = Column(PGUUID(as_uuid=True).with_variant(String(36), "sqlite"),
                           primary_key=True, default=_uuid)
    run_id        = Column(PGUUID(as_uuid=True).with_variant(String(36), "sqlite"),
                           ForeignKey("test_runs.id"), nullable=False)
    site_name     = Column(String(50), nullable=False)
    filename      = Column(String(255), nullable=False)
    downloaded_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # relationships
    run = relationship("TestRun")

    def __repr__(self):
        return f"<KpiDownloadHistory {self.filename} downloaded at {self.downloaded_at}>"
