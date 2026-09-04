"""Gateway config - env only, no config files.

The submit key is a SECRET: it is compared with hmac.compare_digest and is never logged.
`Config.redacted_items()` is the ONLY sanctioned way to print config at startup - it drops the
key entirely rather than masking it, so a formatting slip can never leak even a prefix.

fail_closed_startup is called before the app binds a port: an unset or short key aborts the
process (the server refuses to start). This is a startup guard, not a request-path
check, so the failure is loud and early rather than a 500 on first upload.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Minimum submit-key length. Shorter keys are refused at startup, not accepted-then-weak.
_MIN_KEY_LEN = 16

# Default max upload size, MB. The SINGLE SOURCE for this default: the runner imports it for its
# extraction byte cap rather than carrying its own 250 literal, so
# the two can never silently drift (they must agree — the runner's cap derives from the gateway's
# upload-time 4x-total rule). Overridable per-deployment via AUSMT_MAX_UPLOAD_MB.
DEFAULT_MAX_UPLOAD_MB = 250


@dataclass(frozen=True)
class Config:
    submit_key: str
    data_dir: Path
    max_upload_mb: int
    max_inflight: int
    max_per_day: int
    job_timeout_s: int
    clamd_host: str
    clamd_port: int
    # Curator config. curator_keys is the RAW `name:key,name:key` string; it is
    # parsed (and its fail-closed check applied) in curator_auth, not here — config stays a dumb
    # env carrier. It is a SECRET and is dropped from redacted_items below, never logged.
    curator_keys: str = ""
    surveys_live_dir: Path | None = None
    session_ttl_s: int = 12 * 3600
    login_max_attempts: int = 5
    login_window_s: int = 300
    # Metadata editor: how long the gateway's edit seam polls jobs/edit/done/ for the gw-runner's
    # result before surfacing a retryable error to the curator. Bounded by design — the gw-runner may
    # be mid-validation of a long submission job (its loop is single-threaded).
    edit_timeout_s: int = 120
    # Self-serve key issuance. The public POST /gateway/request-key mints an email_verified
    # uploader key and mails it. These are all SECONDARY to the operator-issued path (which stays the
    # env AUSMT_SUBMIT_KEY + curator-issued DB keys); every value has a working default so a deploy
    # that does not configure SMTP simply runs with issuance disabled (the endpoint still 202s).
    #
    # SMTP: smtp_pass is a SECRET (dropped from redacted_items, never logged). An unset smtp_host OR
    # mail_from means mail is NOT configured — mail_configured is False and the endpoint logs
    # "issuance disabled" and mints nothing.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    mail_from: str = ""
    # The public submit-page URL woven into the issued-key email so the contributor knows where to go.
    # Empty => the email omits the link line rather than printing a broken one.
    submit_page_url: str = ""
    # Daily issuance rate limits (fail-closed, persisted in the gateway DB so they survive a restart).
    # Counts are per UTC day of ALLOWED (recorded) requests: an over-cap request silently does nothing
    # and returns the same neutral 202 (no rate-limit disclosure). per-email caps issuance to one
    # address; per-ip is defence-in-depth (behind a reverse proxy it is the proxy hop — see the
    # request-key handler note); global is the absolute daily backstop.
    key_request_per_email_daily: int = 3
    key_request_per_ip_daily: int = 20
    key_request_global_daily: int = 200
    # email_verified key shape: default 14-day expiry and a 5-submission allowance (both enforced on
    # the submit path; an expired or exhausted key is rejected with the SAME 401 as an invalid key).
    email_verified_key_expiry_days: int = 14
    email_verified_key_allowance: int = 5

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def mail_configured(self) -> bool:
        """True only when BOTH the SMTP host and the From address are set — the minimum to reach a
        mailbox. When False the self-serve request-key endpoint mints nothing and logs that issuance
        is disabled (it still returns the neutral 202). User/pass may be empty (an unauthenticated
        relay or a localhost submission port is legitimate)."""
        return bool(self.smtp_host.strip() and self.mail_from.strip())

    # Directory layout under data_dir (host tree). These are the gateway's view; the
    # runner sees incoming ro / quarantine rw / jobs rw under its own mount at the same relative
    # names, so the runner recomputes them from its own AUSMT_GW_DATA and never trusts a path
    # handed to it in a job file beyond confirming containment.
    @property
    def incoming_dir(self) -> Path:
        return self.data_dir / "incoming"

    @property
    def quarantine_dir(self) -> Path:
        return self.data_dir / "quarantine"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def state_dir(self) -> Path:
        return self.data_dir / "state"

    @property
    def db_path(self) -> Path:
        return self.state_dir / "gateway.sqlite"

    def redacted_items(self) -> list[tuple[str, str]]:
        """Config for the startup log: submit_key AND curator_keys intentionally DROPPED, never
        masked, dropped, so a formatting slip cannot leak even a prefix. The curator-count
        is logged instead of the keys so the operator can confirm curators are configured without the
        secrets appearing anywhere in the log stream."""
        curators_configured = len([p for p in self.curator_keys.split(",") if p.strip()])
        return [
            ("AUSMT_GW_DATA", str(self.data_dir)),
            ("AUSMT_MAX_UPLOAD_MB", str(self.max_upload_mb)),
            ("AUSMT_MAX_INFLIGHT", str(self.max_inflight)),
            ("AUSMT_MAX_PER_DAY", str(self.max_per_day)),
            ("AUSMT_JOB_TIMEOUT_S", str(self.job_timeout_s)),
            ("AUSMT_CLAMD_HOST", self.clamd_host),
            ("AUSMT_CLAMD_PORT", str(self.clamd_port)),
            ("AUSMT_SURVEYS_LIVE", str(self.surveys_live_dir) if self.surveys_live_dir else "<unset>"),
            ("AUSMT_SESSION_TTL_S", str(self.session_ttl_s)),
            ("AUSMT_EDIT_TIMEOUT_S", str(self.edit_timeout_s)),
            ("AUSMT_CURATORS_CONFIGURED", str(curators_configured)),
            ("AUSMT_SMTP_HOST", self.smtp_host or "<unset>"),
            ("AUSMT_SMTP_PORT", str(self.smtp_port)),
            ("AUSMT_SMTP_USER", self.smtp_user or "<unset>"),
            ("AUSMT_MAIL_FROM", self.mail_from or "<unset>"),
            ("AUSMT_MAIL_CONFIGURED", str(self.mail_configured)),
            ("AUSMT_SUBMIT_KEY", "<redacted>"),
            ("AUSMT_CURATOR_KEYS", "<redacted>"),
            ("AUSMT_SMTP_PASS", "<redacted>"),
        ]


def load_config(environ: dict[str, str] | None = None) -> Config:
    """Build Config from the environment. Does NOT enforce the key guard — call
    fail_closed_startup for that so tests can construct a Config with a deliberately weak key to
    exercise the guard itself."""
    env = os.environ if environ is None else environ

    def _i(name: str, default: int) -> int:
        raw = env.get(name)
        return default if raw is None or raw == "" else int(raw)

    surveys_live = env.get("AUSMT_SURVEYS_LIVE", "")
    return Config(
        submit_key=env.get("AUSMT_SUBMIT_KEY", ""),
        data_dir=Path(env.get("AUSMT_GW_DATA", "/gw")),
        max_upload_mb=_i("AUSMT_MAX_UPLOAD_MB", DEFAULT_MAX_UPLOAD_MB),
        max_inflight=_i("AUSMT_MAX_INFLIGHT", 8),
        max_per_day=_i("AUSMT_MAX_PER_DAY", 25),
        job_timeout_s=_i("AUSMT_JOB_TIMEOUT_S", 900),
        clamd_host=env.get("AUSMT_CLAMD_HOST", "clamd"),
        clamd_port=_i("AUSMT_CLAMD_PORT", 3310),
        curator_keys=env.get("AUSMT_CURATOR_KEYS", ""),
        surveys_live_dir=Path(surveys_live) if surveys_live else None,
        session_ttl_s=_i("AUSMT_SESSION_TTL_S", 12 * 3600),
        login_max_attempts=_i("AUSMT_LOGIN_MAX_ATTEMPTS", 5),
        login_window_s=_i("AUSMT_LOGIN_WINDOW_S", 300),
        edit_timeout_s=_i("AUSMT_EDIT_TIMEOUT_S", 120),
        smtp_host=env.get("AUSMT_SMTP_HOST", ""),
        smtp_port=_i("AUSMT_SMTP_PORT", 587),
        smtp_user=env.get("AUSMT_SMTP_USER", ""),
        smtp_pass=env.get("AUSMT_SMTP_PASS", ""),
        mail_from=env.get("AUSMT_MAIL_FROM", ""),
        submit_page_url=env.get("AUSMT_SUBMIT_PAGE_URL", ""),
        key_request_per_email_daily=_i("AUSMT_KEYREQ_PER_EMAIL_DAILY", 3),
        key_request_per_ip_daily=_i("AUSMT_KEYREQ_PER_IP_DAILY", 20),
        key_request_global_daily=_i("AUSMT_KEYREQ_GLOBAL_DAILY", 200),
        email_verified_key_expiry_days=_i("AUSMT_SELFSERVE_KEY_EXPIRY_DAYS", 14),
        email_verified_key_allowance=_i("AUSMT_SELFSERVE_KEY_ALLOWANCE", 5),
    )


# Container-internal env vars compose FIXES to a container path itself, so they are NOT operator knobs
# forwarded from .env: AUSMT_GW_DATA=/gw and AUSMT_SURVEYS_LIVE=/srv/surveys-live are set inline in the
# gateway service, never `${VAR:-}` passthroughs (see .env.example's closing note "set INSIDE compose").
# Everything else load_config reads IS an operator knob the compose gateway service must forward.
_CONTAINER_FIXED_ENV: frozenset[str] = frozenset({"AUSMT_GW_DATA", "AUSMT_SURVEYS_LIVE"})


def operator_env_vars() -> tuple[str, ...]:
    """The operator-facing AUSMT_* env vars the compose gateway service MUST forward from .env into the
    container (the .env->app bridge). DERIVED, never hand-listed: it records every key load_config()
    actually reads and drops the container-fixed paths above, so a knob newly added to load_config is
    required in compose AUTOMATICALLY. That closes the drift CLASS: the regression pin cannot restate a
    stale copy of config's env surface and stay green while a var is silently dropped. Returned in
    first-read order, de-duplicated."""
    seen: dict[str, None] = {}

    class _Recorder(dict):
        # Every env read in load_config goes through .get; record the AUSMT_* names, return the
        # caller's default so load_config builds a valid Config off an empty environment.
        def get(self, key, default=None):
            if isinstance(key, str) and key.startswith("AUSMT_"):
                seen.setdefault(key, None)
            return default

    load_config(_Recorder())
    return tuple(name for name in seen if name not in _CONTAINER_FIXED_ENV)


# Numeric knobs whose zero or negative value is never a legitimate operator intent, as
# (field, env var, minimum, maximum). Each one fails INVISIBLY at runtime if it is allowed through:
# max_upload_mb=0 is a universal 413, max_inflight=0 a universal 429, session_ttl_s=0 an infinite
# login bounce (total curator lockout), and a zeroed daily cap disables self-serve issuance behind
# its by-design neutral 202 - while /gateway/healthz, the compose healthcheck and the portal probe all
# keep reporting green. Issuance is disabled by leaving SMTP unconfigured (mail_configured, which the
# startup log states), never by zeroing a cap. Ports are checked at both ends: 0 and 65536 are not
# ports. The check belongs at startup for the same reason the key guard does - loud and early.
_RANGES: tuple[tuple[str, str, int, int], ...] = (
    ("max_upload_mb", "AUSMT_MAX_UPLOAD_MB", 1, 1024 * 1024),
    ("max_inflight", "AUSMT_MAX_INFLIGHT", 1, 1_000_000),
    ("max_per_day", "AUSMT_MAX_PER_DAY", 1, 1_000_000),
    ("job_timeout_s", "AUSMT_JOB_TIMEOUT_S", 1, 86_400),
    ("clamd_port", "AUSMT_CLAMD_PORT", 1, 65_535),
    ("session_ttl_s", "AUSMT_SESSION_TTL_S", 1, 365 * 86_400),
    ("login_max_attempts", "AUSMT_LOGIN_MAX_ATTEMPTS", 1, 1_000_000),
    ("login_window_s", "AUSMT_LOGIN_WINDOW_S", 1, 365 * 86_400),
    ("edit_timeout_s", "AUSMT_EDIT_TIMEOUT_S", 1, 86_400),
    ("smtp_port", "AUSMT_SMTP_PORT", 1, 65_535),
    ("key_request_per_email_daily", "AUSMT_KEYREQ_PER_EMAIL_DAILY", 1, 1_000_000),
    ("key_request_per_ip_daily", "AUSMT_KEYREQ_PER_IP_DAILY", 1, 1_000_000),
    ("key_request_global_daily", "AUSMT_KEYREQ_GLOBAL_DAILY", 1, 1_000_000),
    ("email_verified_key_expiry_days", "AUSMT_SELFSERVE_KEY_EXPIRY_DAYS", 1, 3_650),
    ("email_verified_key_allowance", "AUSMT_SELFSERVE_KEY_ALLOWANCE", 1, 1_000_000),
)


def fail_closed_startup(cfg: Config) -> None:
    """Refuse to start on a missing/short submit key or an out-of-range numeric knob
    (_RANGES). Raises SystemExit, so the port is never bound and there is no window where the gateway
    accepts uploads with a weak key or serves a wall of 413/429 while its health surfaces read green.
    The key is checked FIRST so a deploy that is both key-less and mis-tuned names the secret."""
    if len(cfg.submit_key) < _MIN_KEY_LEN:
        raise SystemExit(
            f"AUSMT_SUBMIT_KEY must be set and >= {_MIN_KEY_LEN} chars (fail closed, design §3)"
        )
    for field, env_name, low, high in _RANGES:
        value = getattr(cfg, field)
        if not low <= value <= high:
            raise SystemExit(
                f"{env_name} ({field}) must be between {low} and {high}, got {value} "
                "(fail closed: an out-of-range knob breaks the gateway silently)"
            )
