"""One additive migration; old assets and request/billing history stay intact."""


def migrate(db):
    version = db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0]
    if version == "2":
        return
    if version != "1":
        raise RuntimeError("unsupported schema: migration required")
    db.execute("BEGIN IMMEDIATE")
    try:
        for table, columns in {
            "samples": ["review_format_retries INTEGER NOT NULL DEFAULT 0", "runtime_config_hash TEXT"],
            "campaigns": ["runtime_config_hash TEXT"],
            "attempts": ["capacity_group TEXT", "execution_deadline REAL", "execution_evidence TEXT",
                         "response_applied INTEGER NOT NULL DEFAULT 0", "runtime_config_hash TEXT"],
            "dedup_features": ["upright_hash TEXT"],
        }.items():
            for column in columns:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
        db.execute("UPDATE attempts SET capacity_group='legacy:' || endpoint_alias")
        db.execute("UPDATE attempts SET response_applied=1 WHERE NOT EXISTS (SELECT 1 FROM samples s WHERE s.attempt_id=attempts.attempt_id AND s.revision=attempts.revision AND s.stage=attempts.role)")
        db.executescript("""
        CREATE INDEX attempts_occupied ON attempts(capacity_group,campaign_id,status) WHERE occupancy=1;
        CREATE INDEX attempts_recent ON attempts(capacity_group,started_at,reserved_tokens);
        CREATE INDEX attempts_running ON attempts(campaign_id) WHERE status='running';
        CREATE INDEX attempts_pending_response ON attempts(sample_id,revision) WHERE response_applied=0;
        CREATE INDEX samples_pending ON samples(campaign_id,stage,updated_at,next_ready_at) WHERE status IN ('ready','deferred');
        CREATE INDEX samples_inflight ON samples(campaign_id,stage,status) WHERE status IN ('ready','running','deferred');
        CREATE INDEX samples_page ON samples(campaign_id,sample_id);
        CREATE INDEX assets_recent ON assets(campaign_id,created_at) WHERE accepted_unique=1;
        CREATE INDEX assets_lineage ON assets(lineage_group,is_current);
        CREATE INDEX dedup_upright ON dedup_features(upright_hash);
        CREATE TABLE family_health (
          campaign_id TEXT NOT NULL,family_id TEXT NOT NULL,failures INTEGER NOT NULL DEFAULT 0,
          last_failure_at REAL NOT NULL DEFAULT 0,PRIMARY KEY(campaign_id,family_id));
        CREATE TABLE config_snapshots (
          config_hash TEXT PRIMARY KEY,profile_hash TEXT NOT NULL,config_json TEXT NOT NULL,created_at REAL NOT NULL);
        CREATE TABLE config_history (
          campaign_id TEXT NOT NULL,revision INTEGER NOT NULL,config_hash TEXT NOT NULL,
          campaign_json TEXT NOT NULL,created_at REAL NOT NULL,PRIMARY KEY(campaign_id,revision));
        CREATE TABLE seed_stats (
          campaign_id TEXT NOT NULL,family_id TEXT NOT NULL,theme_seed_id TEXT NOT NULL,
          accepted INTEGER NOT NULL DEFAULT 0,active INTEGER NOT NULL DEFAULT 0,
          rejected INTEGER NOT NULL DEFAULT 0,duplicate INTEGER NOT NULL DEFAULT 0,
          provisional INTEGER NOT NULL DEFAULT 0,planned INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(campaign_id,family_id,theme_seed_id));
        INSERT INTO seed_stats
          SELECT campaign_id,family_id,theme_seed_id,SUM(status='accepted'),
            SUM(status IN ('ready','running','deferred','awaiting_review')),
            SUM(status='rejected' AND COALESCE(reason_code,'')!='duplicate'),
            SUM(COALESCE(reason_code,'')='duplicate'),SUM(status='provisional_pass'),COUNT(*)
          FROM samples GROUP BY campaign_id,family_id,theme_seed_id;
        """)
        # Summary updates are in the same SQLite transaction as the source row.
        fields = {
            "accepted": "status='accepted'",
            "active": "status IN ('ready','running','deferred','awaiting_review')",
            "rejected": "status='rejected' AND COALESCE({r}.reason_code,'')!='duplicate'",
            "duplicate": "COALESCE({r}.reason_code,'')='duplicate'",
            "provisional": "status='provisional_pass'",
            "planned": "1",
        }

        def delta(row, sign):
            values = []
            for name, condition in fields.items():
                expression = condition.format(r=row)
                if condition.startswith("status"):
                    expression = row + "." + expression
                values.append(f"{name}={name}{sign}({expression})")
            return f"UPDATE seed_stats SET {','.join(values)} WHERE campaign_id={row}.campaign_id AND family_id={row}.family_id AND theme_seed_id={row}.theme_seed_id;"

        initialize = "INSERT OR IGNORE INTO seed_stats(campaign_id,family_id,theme_seed_id) VALUES(NEW.campaign_id,NEW.family_id,NEW.theme_seed_id);"
        db.executescript(f"""
        CREATE TRIGGER samples_stats_insert AFTER INSERT ON samples BEGIN {initialize} {delta('NEW','+')} END;
        CREATE TRIGGER samples_stats_update AFTER UPDATE OF status,reason_code,campaign_id,family_id,theme_seed_id ON samples
          BEGIN {delta('OLD','-')} {initialize} {delta('NEW','+')} END;
        CREATE TRIGGER samples_stats_delete AFTER DELETE ON samples BEGIN {delta('OLD','-')} END;
        UPDATE meta SET value='2' WHERE key='schema';
        """)
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
